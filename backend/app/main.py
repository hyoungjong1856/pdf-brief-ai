import asyncio
import time
from io import BytesIO
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader

from app.evaluation import calculate_cer, get_text_length_metrics
from app.hybrid_service import ImageOcrError, extract_document, has_text_layer
from app.image_ocr import IMAGE_OCR_MODEL, IMAGE_OCR_NUM_CTX, IMAGE_OCR_TIMEOUT
from app.layout import paddle_status
from app.ollama_service import (
    ANALYSIS_MODEL_NAME,
    ANALYSIS_TIMEOUT,
    SUMMARY_MODEL_NAME,
    SUMMARY_TIMEOUT,
    ModelResponseError,
    analyze_pdf,
    summarize_text,
)
from app.schemas import PDFSummaryResponse

app = FastAPI(
    title="PDF Brief AI API",
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


def read_pdf_diagnostics(file_bytes: bytes) -> tuple[int, int, int]:
    """PDF의 페이지·표·이미지 개수를 진단용으로 확인합니다."""

    reader = PdfReader(BytesIO(file_bytes))
    table_count = 0
    image_count = 0

    for page in reader.pages:
        # pypdf의 선 기반 표 탐지는 표가 없거나 비정형 PDF에서도 예외를 낼 수 있어,
        # 진단 정보 수집 실패가 문서 분석 전체를 중단시키지 않도록 분리합니다.
        try:
            table_count += len(page.extract_tables())
        except Exception:
            pass

        try:
            image_count += len(page.images)
        except Exception:
            pass

    return len(reader.pages), table_count, image_count


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
    "/ai/pdf",
    response_model=PDFSummaryResponse,
)
async def pdf_summary(
    file: UploadFile = File(...),
    ground_truth: UploadFile | None = File(None),
    method: Literal["auto", "hybrid", "vlm"] = Query(
        "auto",
        description=(
            "auto: 텍스트 레이어가 있으면 hybrid, 없으면 vlm / "
            "hybrid: 레이아웃 판단 + PyMuPDF 본문 + PaddleOCR-VL 이미지 / "
            "vlm: 페이지 전체를 비전 모델 한 번에"
        ),
    ),
) -> PDFSummaryResponse:
    """PDF를 추출·요약하고 평가 지표를 함께 반환합니다."""

    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="PDF 파일만 업로드할 수 있습니다.",
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="비어 있는 PDF 파일입니다.",
        )

    started_at = time.perf_counter()

    try:
        page_count, table_count, image_count = read_pdf_diagnostics(file_bytes)
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="PDF 파일을 읽는 데 실패했습니다.",
        ) from error

    resolved = method
    if method == "auto":
        try:
            resolved = "hybrid" if await asyncio.to_thread(has_text_layer, file_bytes) else "vlm"
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail="PDF 파일을 읽는 데 실패했습니다.",
            ) from error

    if resolved == "hybrid":
        response = await run_hybrid(file_bytes, page_count)
    else:
        response = await run_vlm(file_bytes)

    text = response["extracted_text"]
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF에서 텍스트를 추출하지 못했습니다.",
        )

    cer = None
    text_length_metrics = get_text_length_metrics(text)
    if ground_truth:
        ground_truth_text = await read_ground_truth(ground_truth)
        cer = calculate_cer(ground_truth_text, text)
        text_length_metrics = get_text_length_metrics(text, ground_truth_text)

    extraction_time_ms = round((time.perf_counter() - started_at) * 1000, 2)

    return PDFSummaryResponse(
        filename=file.filename or "uploaded.pdf",
        extraction_time_ms=extraction_time_ms,
        page_count=page_count,
        table_count=table_count,
        image_count=image_count,
        cer=cer,
        method=resolved,
        **text_length_metrics,
        **response,
    )


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
            detail=f"PDF 추출에 실패했습니다: {error}",
        ) from error

    if not result.text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF에서 텍스트를 추출하지 못했습니다.",
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