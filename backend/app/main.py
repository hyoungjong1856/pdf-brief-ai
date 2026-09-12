import asyncio
import time
from io import BytesIO

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader

from app.ollama_service import (
    OCR_MODEL_NAME,
    SUMMARY_MODEL_NAME,
    extract_keywords_and_summary,
    extract_text_with_ocr,
)
from app.schemas import PDFSummaryResponse

app = FastAPI(
    title="PDF Brief AI API",
    version="1.0.0",
)

# React 개발 서버가 FastAPI에 요청할 수 있도록 허용합니다.
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


def extract_text_from_pdf(
    file_bytes: bytes,
) -> tuple[str, int, int, int]:
    """PDF의 내장 텍스트와 개발자용 진단 정보를 함께 추출합니다."""

    reader = PdfReader(BytesIO(file_bytes))
    text_parts: list[str] = []
    table_count = 0
    image_count = 0

    for page in reader.pages:
        page_text = page.extract_text()

        if page_text:
            text_parts.append(page_text)

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

    return "\n".join(text_parts), len(reader.pages), table_count, image_count


def should_use_ocr(
    text: str,
    page_count: int,
) -> bool:
    """페이지당 추출 글자 수가 너무 적으면 스캔 PDF로 보고 OCR을 사용합니다."""

    text_length = len(text.strip())
    characters_per_page = text_length / max(page_count, 1)

    # 페이지당 100자 미만이면 텍스트가 거의 없는 스캔본으로 간주합니다.
    return characters_per_page < 100


@app.post(
    "/ai/pdf",
    response_model=PDFSummaryResponse,
)
async def pdf_summary(
    file: UploadFile = File(...),
) -> PDFSummaryResponse:
    """PDF를 받고, 텍스트 추출 또는 OCR 후 키워드와 요약을 반환합니다."""

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

    extraction_started_at = time.perf_counter()

    try:
        # 1차: 텍스트 기반 PDF에서 빠르고 정확하게 원본 텍스트를 추출합니다.
        extracted_text, page_count, table_count, image_count = extract_text_from_pdf(
            file_bytes,
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="PDF 파일을 읽는 데 실패했습니다.",
        ) from error

    if True:  # 항상 OCR을 사용하도록 설정 (개발용)
        extraction_method = "glm-ocr"
        extraction_model = OCR_MODEL_NAME or "glm-ocr"

        try:
            # 2차: 텍스트가 거의 없는 스캔 PDF만 OCR 모델에 보냅니다.
            text = await asyncio.to_thread(
                extract_text_with_ocr,
                file_bytes,
            )
        except httpx.HTTPError as error:
            print(f"로컬 GLM-OCR 모델 요청 오류: {error}")
            raise HTTPException(
                status_code=502,
                # detail="로컬 GLM-OCR 모델 요청에 실패했습니다.",
                detail=f"로컬 GLM-OCR 모델 요청에 실패했습니다: {error}",
            ) from error
    else:
        extraction_method = "pypdf"
        extraction_model = "pypdf"
        text = extracted_text

    extraction_time_ms = round(
        (time.perf_counter() - extraction_started_at) * 1000,
        2,
    )

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF에서 텍스트를 추출하지 못했습니다.",
        )

    try:
        # 추출된 텍스트를 Qwen 모델에 보내 키워드와 요약을 생성합니다.
        result = await asyncio.to_thread(
            extract_keywords_and_summary,
            text,
        )
    except httpx.HTTPError as error:
        print(f"로컬 요약 모델 요청 오류: {error}")
        raise HTTPException(
            status_code=502,
            # detail="로컬 요약 모델 요청에 실패했습니다.",
            detail=f"로컬 모델 요청에 실패했습니다: {error}",
        ) from error

    return PDFSummaryResponse(
        filename=file.filename or "uploaded.pdf",
        model=SUMMARY_MODEL_NAME,
        extraction_model=extraction_model,
        extraction_method=extraction_method,
        extraction_time_ms=extraction_time_ms,
        extracted_text=text,
        page_count=page_count,
        table_count=table_count,
        image_count=image_count,
        keyword=result["keyword"],
        summary=result["summary"],
    )
