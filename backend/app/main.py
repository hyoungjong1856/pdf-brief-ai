import asyncio
import time
from io import BytesIO
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader

from app.evaluation import calculate_cer, get_text_length_metrics
from app.file_ingest import (
    HWP_EXTENSIONS,
    IMAGE_EXTENSIONS,
    OFFICE_EXTENSIONS,
    PLAIN_TEXT_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    extension_of,
    hwp_to_pdf_bytes,
    normalize_image_to_png_bytes,
    office_to_pdf_bytes,
    read_plain_text,
)
from app.hybrid_service import ImageOcrError, extract_document, extract_image_document
from app.image_ocr import IMAGE_OCR_MODEL, IMAGE_OCR_NUM_CTX, IMAGE_OCR_TIMEOUT
from app.layout import paddle_status
from app.ollama_service import (
    ANALYSIS_MODEL_NAME,
    ANALYSIS_TIMEOUT,
    SUMMARY_MODEL_NAME,
    SUMMARY_TIMEOUT,
    ModelResponseError,
    analyze_image,
    analyze_pdf,
    summarize_text,
)
from app.schemas import PDFSummaryResponse

app = FastAPI(
    title="Document Brief AI API",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/capabilities")
def capabilities() -> dict[str, str | float | int | None]:
    """현재 서버가 어떤 구성으로 동작하는지 알려줍니다.

    PaddleOCR 설치 여부를 확인하지 않고 분석을 돌리면 왜 기하 판단으로 떨어졌는지
    알기 어려우므로, 진단용으로 분리해 두었습니다.
    """

    return {
        "layout": paddle_status(),
        "image_ocr_model": IMAGE_OCR_MODEL,
        "summary_model": SUMMARY_MODEL_NAME,
        "vlm_model": ANALYSIS_MODEL_NAME,
        # .env 값이 실제로 반영됐는지 재시작 없이 바로 확인하기 위한 진단용 필드입니다.
        # 여기 찍힌 숫자가 .env에 적은 값과 다르면 .env가 아직 로드되지 않은 것입니다.
        "image_ocr_timeout": IMAGE_OCR_TIMEOUT,
        "image_ocr_num_ctx": IMAGE_OCR_NUM_CTX,
        "summary_timeout": SUMMARY_TIMEOUT,
        "analysis_timeout": ANALYSIS_TIMEOUT,
    }


def read_page_count(file_bytes: bytes) -> int:
    """PDF의 페이지 수를 확인합니다.

    표·이미지 개수는 더 이상 진단 정보로 제공하지 않습니다. pypdf의 선 기반
    표 탐지(extract_tables)는 테두리선 없는 표를 놓치기 쉽고, page.images는
    벡터 차트를 집계하지 못하면서 장식용 이미지는 그대로 세는 등 신뢰도가
    낮아 실제 파이프라인 지표(image_region_count 등)와 혼동을 줄 수 있었습니다.
    """

    reader = PdfReader(BytesIO(file_bytes))
    return len(reader.pages)


async def read_ground_truth(ground_truth: UploadFile) -> str:
    if not (ground_truth.filename or "").lower().endswith(".txt"):
        raise HTTPException(
            status_code=400,
            detail="정답 텍스트는 .txt 파일만 업로드할 수 있습니다.",
        )

    ground_truth_bytes = await ground_truth.read()
    if not ground_truth_bytes:
        raise HTTPException(
            status_code=400,
            detail="정답 텍스트 파일이 비어 있습니다.",
        )

    try:
        return ground_truth_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="정답 텍스트 파일은 UTF-8 인코딩이어야 합니다.",
        ) from error


@app.post(
    "/ai/document",
    response_model=PDFSummaryResponse,
)
async def document_summary(
    file: UploadFile = File(...),
    ground_truth: UploadFile | None = File(None),
    method: Literal["hybrid", "vlm"] = Query(
        "hybrid",
        description=(
            "hybrid (기본값): 레이아웃 판단 + PyMuPDF 본문 + PaddleOCR-VL 이미지. "
            "텍스트 레이어가 없는 페이지는 자동으로 전면 OCR 처리됩니다 / "
            "vlm: 페이지 전체를 비전 모델 한 번에 넘기는 비교용 경로"
        ),
    ),
) -> PDFSummaryResponse:
    """문서를 추출·요약하고 평가 지표를 함께 반환합니다."""

    filename = file.filename or "uploaded"
    extension = extension_of(filename)

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"지원하지 않는 파일 형식입니다: {extension or '(확장자 없음)'}. "
                f"지원 형식: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="비어 있는 파일입니다.",
        )

    started_at = time.perf_counter()

    if extension in PLAIN_TEXT_EXTENSIONS:
        # 텍스트 파일은 레이아웃·OCR이 필요 없으므로 요약 단계로 바로 직행합니다.
        # page_count 등 PDF 전용 진단 필드는 의미가 없어 1/None으로 고정됩니다.
        text_input = read_plain_text(file_bytes)
        if not text_input.strip():
            raise HTTPException(
                status_code=422,
                detail="파일에서 텍스트를 추출하지 못했습니다.",
            )
        response = await run_text(text_input)
        page_count = 1
    elif extension in IMAGE_EXTENSIONS:
        # 이미지는 페이지·레이아웃 개념이 없으므로 PDF로 감쌌다가 다시 여는
        # 왕복 없이 정규화한 PNG 바이트를 바로 OCR 경로로 넘깁니다.
        png_bytes = await asyncio.to_thread(normalize_image_to_png_bytes, file_bytes)
        page_count = 1

        if method == "hybrid":
            response = await run_hybrid_image(png_bytes)
        else:
            response = await run_vlm_image(png_bytes)
    else:
        if extension in HWP_EXTENSIONS:
            hwp_to_pdf_bytes(filename, file_bytes)  # 항상 501을 던집니다.

        if extension in OFFICE_EXTENSIONS:
            pdf_bytes = await asyncio.to_thread(office_to_pdf_bytes, filename, file_bytes)
        else:  # .pdf
            pdf_bytes = file_bytes

        try:
            page_count = read_page_count(pdf_bytes)
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail="파일을 읽는 데 실패했습니다.",
            ) from error

        if method == "hybrid":
            response = await run_hybrid(pdf_bytes, page_count)
        else:
            response = await run_vlm(pdf_bytes)

    text = response["extracted_text"]
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="파일에서 텍스트를 추출하지 못했습니다.",
        )

    cer = None
    text_length_metrics = get_text_length_metrics(text)
    if ground_truth:
        ground_truth_text = await read_ground_truth(ground_truth)
        cer = calculate_cer(ground_truth_text, text)
        text_length_metrics = get_text_length_metrics(text, ground_truth_text)

    extraction_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response_method = "text" if extension in PLAIN_TEXT_EXTENSIONS else method

    return PDFSummaryResponse(
        filename=filename,
        extraction_time_ms=extraction_time_ms,
        page_count=page_count,
        cer=cer,
        method=response_method,
        **text_length_metrics,
        **response,
    )


async def run_text(text: str) -> dict:
    """.txt/.md 전용 경로 — 레이아웃·OCR 없이 텍스트를 바로 요약합니다."""

    summary_started = time.perf_counter()
    try:
        summarized = await asyncio.to_thread(summarize_text, text)
    except (httpx.HTTPError, ModelResponseError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"{SUMMARY_MODEL_NAME} 요약 요청에 실패했습니다: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    summary_time_ms = round((time.perf_counter() - summary_started) * 1000, 2)

    return {
        "model": SUMMARY_MODEL_NAME,
        "extraction_model": None,
        "extraction_method": "text | direct passthrough (레이아웃·OCR 없음)",
        "extracted_text": text,
        "keyword": summarized["keyword"],
        "summary": summarized["summary"],
        "summary_model": SUMMARY_MODEL_NAME,
        "summary_time_ms": summary_time_ms,
        "warnings": [],
    }


async def run_hybrid(file_bytes: bytes, page_count: int) -> dict:
    """레이아웃 판단 → 본문 추출 → 이미지 OCR → 요약 순으로 처리합니다."""

    try:
        result = await asyncio.to_thread(extract_document, file_bytes)
    except ImageOcrError as error:
        # 이미지 안에만 있는 문장은 다른 수단으로 복구할 수 없으므로,
        # 일부만 담긴 결과를 성공으로 돌려주지 않고 실패를 그대로 드러냅니다.
        raise HTTPException(
            status_code=502,
            detail=f"이미지 영역 OCR에 실패했습니다: {error}",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"문서 추출에 실패했습니다: {error}",
        ) from error

    if not result.text.strip():
        raise HTTPException(
            status_code=422,
            detail="문서에서 텍스트를 추출하지 못했습니다.",
        )

    summary_started = time.perf_counter()
    try:
        summarized = await asyncio.to_thread(summarize_text, result.text)
    except (httpx.HTTPError, ModelResponseError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"{SUMMARY_MODEL_NAME} 요약 요청에 실패했습니다: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    summary_time_ms = round((time.perf_counter() - summary_started) * 1000, 2)

    extraction_method = (
        f"hybrid | layout={result.layout_source} | "
        f"text=pymupdf | image={IMAGE_OCR_MODEL}"
    )

    return {
        "model": SUMMARY_MODEL_NAME,
        "extraction_model": IMAGE_OCR_MODEL,
        "extraction_method": extraction_method,
        "extracted_text": result.text,
        "keyword": summarized["keyword"],
        "summary": summarized["summary"],
        "layout_source": result.layout_source,
        "summary_model": SUMMARY_MODEL_NAME,
        "image_ocr_model": IMAGE_OCR_MODEL,
        "image_region_count": result.image_region_count,
        "ocr_region_count": result.ocr_region_count,
        "orphan_block_count": result.orphan_block_count,
        "scanned_page_count": result.scanned_page_count,
        "layout_time_ms": result.layout_time_ms,
        "ocr_time_ms": result.ocr_time_ms,
        "summary_time_ms": summary_time_ms,
        "warnings": result.warnings,
    }


async def run_hybrid_image(png_bytes: bytes) -> dict:
    """이미지 파일 전용 hybrid 경로 — PDF 변환 없이 바로 OCR합니다."""

    try:
        result = await asyncio.to_thread(extract_image_document, png_bytes)
    except ImageOcrError as error:
        raise HTTPException(
            status_code=502,
            detail=f"이미지 OCR에 실패했습니다: {error}",
        ) from error

    if not result.text.strip():
        raise HTTPException(
            status_code=422,
            detail="이미지에서 텍스트를 추출하지 못했습니다.",
        )

    summary_started = time.perf_counter()
    try:
        summarized = await asyncio.to_thread(summarize_text, result.text)
    except (httpx.HTTPError, ModelResponseError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"{SUMMARY_MODEL_NAME} 요약 요청에 실패했습니다: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    summary_time_ms = round((time.perf_counter() - summary_started) * 1000, 2)

    extraction_method = f"hybrid | image=direct(PDF 변환 없음) | image={IMAGE_OCR_MODEL}"

    return {
        "model": SUMMARY_MODEL_NAME,
        "extraction_model": IMAGE_OCR_MODEL,
        "extraction_method": extraction_method,
        "extracted_text": result.text,
        "keyword": summarized["keyword"],
        "summary": summarized["summary"],
        "layout_source": result.layout_source,
        "summary_model": SUMMARY_MODEL_NAME,
        "image_ocr_model": IMAGE_OCR_MODEL,
        "image_region_count": result.image_region_count,
        "ocr_region_count": result.ocr_region_count,
        "orphan_block_count": result.orphan_block_count,
        "scanned_page_count": result.scanned_page_count,
        "layout_time_ms": result.layout_time_ms,
        "ocr_time_ms": result.ocr_time_ms,
        "summary_time_ms": summary_time_ms,
        "warnings": result.warnings,
    }


async def run_vlm_image(png_bytes: bytes) -> dict:
    """이미지 파일 전용 vlm 경로 — PDF 변환 없이 이미지 한 장을 그대로 보냅니다."""

    try:
        result = await asyncio.to_thread(analyze_image, png_bytes)
    except (httpx.HTTPError, ModelResponseError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"로컬 모델의 추출·요약 요청에 실패했습니다: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "model": ANALYSIS_MODEL_NAME or "",
        "extraction_model": ANALYSIS_MODEL_NAME or "",
        "extraction_method": f"vlm | image=direct(PDF 변환 없음) | {ANALYSIS_MODEL_NAME}",
        "extracted_text": result["extracted_text"],
        "keyword": result["keyword"],
        "summary": result["summary"],
        "summary_model": ANALYSIS_MODEL_NAME,
        "warnings": [],
    }


async def run_vlm(file_bytes: bytes) -> dict:
    """페이지 전체를 비전 모델 한 번에 넘기는 기존 방식입니다."""

    try:
        result = await asyncio.to_thread(analyze_pdf, file_bytes)
    except (httpx.HTTPError, ModelResponseError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"로컬 모델의 추출·요약 요청에 실패했습니다: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "model": ANALYSIS_MODEL_NAME or "",
        "extraction_model": ANALYSIS_MODEL_NAME or "",
        "extraction_method": f"vlm | full-page | {ANALYSIS_MODEL_NAME}",
        "extracted_text": result["extracted_text"],
        "keyword": result["keyword"],
        "summary": result["summary"],
        "summary_model": ANALYSIS_MODEL_NAME,
        "warnings": [],
    }