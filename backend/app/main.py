import asyncio
import base64
import time

import fitz
import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    MAX_FILE_SIZE,
    MAX_PAGE_COUNT,
    MIN_DRAWING_COUNT,
    MIN_IMAGE_COUNT,
    OCR_DPI,
    OCR_MODEL_NAME,
    SUMMARY_MODEL_NAME,
)
from app.ollama_service import analyze_document, ocr_page_images
from app.schemas import PdfAnalysisResponse

app = FastAPI(
    title="PDF Brief AI API",
    version="1.0.0",
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
    """서버가 실행 중인지 확인하는 간단한 상태 점검 API입니다."""

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# PDF 판정 / 추출
# ---------------------------------------------------------------------------


def inspect_pdf(document: fitz.Document) -> tuple[int, int]:
    """문서 전체의 내장 이미지 개수와 벡터 드로잉 개수를 셉니다."""

    image_count = 0
    drawing_count = 0

    for page in document:
        image_count += len(page.get_images(full=True))
        drawing_count += len(page.get_drawings())

    return image_count, drawing_count


def is_image_based(image_count: int, drawing_count: int) -> bool:
    """이미지 기반 PDF인지 판정합니다.

    내장 이미지가 있거나, 이미지가 없더라도 벡터 드로잉이 일정 개수 이상이면
    (도면이나 벡터로 출력된 표/차트) 텍스트 추출만으로는 내용을 담을 수 없다고 보고
    OCR 경로로 보냅니다.
    """

    return image_count >= MIN_IMAGE_COUNT or drawing_count >= MIN_DRAWING_COUNT


def extract_text(document: fitz.Document) -> str:
    """텍스트 기반 PDF에서 PyMuPDF로 내장 텍스트를 추출합니다."""

    text_parts: list[str] = []

    for page in document:
        page_text = page.get_text().strip()

        if page_text:
            text_parts.append(page_text)

    return "\n\n".join(text_parts)


def render_page_images(document: fitz.Document) -> list[str]:
    """OCR 모델에 보낼 수 있도록 각 페이지를 Base64 PNG로 렌더링합니다."""

    page_images: list[str] = []

    for page in document:
        pixmap = page.get_pixmap(
            dpi=OCR_DPI,
            alpha=False,
        )
        page_images.append(
            base64.b64encode(pixmap.tobytes("png")).decode("utf-8"),
        )

    return page_images


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@app.post(
    "/ai/pdf",
    response_model=PdfAnalysisResponse,
)
async def analyze_pdf(
    file: UploadFile = File(...),
) -> PdfAnalysisResponse:
    """PDF를 받아 이미지/텍스트 기반을 판정한 뒤 본문·요약·키워드를 반환합니다."""

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="비어 있는 PDF 파일입니다.",
        )

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"파일은 {MAX_FILE_SIZE // (1024 * 1024)}MB 이하여야 합니다.",
        )

    # content_type은 클라이언트가 보내는 값이라 신뢰할 수 없으므로
    # 파일 시그니처로 실제 PDF인지 확인합니다.
    if b"%PDF-" not in file_bytes[:1024]:
        raise HTTPException(
            status_code=400,
            detail="PDF 파일만 업로드할 수 있습니다.",
        )

    extraction_started_at = time.perf_counter()

    try:
        document = fitz.open(
            stream=file_bytes,
            filetype="pdf",
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="PDF 파일을 읽는 데 실패했습니다.",
        ) from error

    try:
        page_count = document.page_count

        if page_count > MAX_PAGE_COUNT:
            raise HTTPException(
                status_code=413,
                detail=f"{MAX_PAGE_COUNT}페이지 이하의 문서만 분석할 수 있습니다.",
            )

        image_count, drawing_count = inspect_pdf(document)
        use_ocr = is_image_based(image_count, drawing_count)

        if use_ocr:
            # 이미지 기반: 페이지를 렌더링해 OCR 모델에 넘깁니다.
            page_images = render_page_images(document)
            source_text = ""
        else:
            # 텍스트 기반: PyMuPDF로 바로 추출합니다.
            page_images = []
            source_text = extract_text(document)
    finally:
        document.close()

    if use_ocr:
        extraction_method = "image"
        extraction_model = OCR_MODEL_NAME

        try:
            source_text = await asyncio.to_thread(
                ocr_page_images,
                page_images,
            )
        except httpx.HTTPError as error:
            print(f"OCR 모델 요청 오류: {error}")
            raise HTTPException(
                status_code=502,
                detail="로컬 OCR 모델 요청에 실패했습니다.",
            ) from error
    else:
        extraction_method = "text"
        extraction_model = "pymupdf"

    extraction_time_ms = round(
        (time.perf_counter() - extraction_started_at) * 1000,
        2,
    )

    if not source_text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF에서 텍스트를 추출하지 못했습니다.",
        )

    try:
        content = await asyncio.to_thread(
            analyze_document,
            source_text,
        )
    except httpx.HTTPError as error:
        print(f"요약 모델 요청 오류: {error}")
        raise HTTPException(
            status_code=502,
            detail="로컬 요약 모델 요청에 실패했습니다.",
        ) from error

    return PdfAnalysisResponse(
        filename=file.filename or "uploaded.pdf",
        model=SUMMARY_MODEL_NAME,
        extraction_model=extraction_model,
        extraction_method=extraction_method,
        extraction_time_ms=extraction_time_ms,
        page_count=page_count,
        image_count=image_count,
        drawing_count=drawing_count,
        document=content.document,
        summary=content.summary,
        keyword=content.keyword,
    )