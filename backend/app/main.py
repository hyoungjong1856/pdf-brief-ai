import asyncio
import time
from io import BytesIO

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader

from app.evaluation import calculate_cer, get_text_length_metrics
from app.ollama_service import (
    ANALYSIS_MODEL_NAME,
    ModelResponseError,
    analyze_pdf,
)
from app.schemas import PDFSummaryResponse

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


@app.post(
    "/ai/pdf",
    response_model=PDFSummaryResponse,
)
async def pdf_summary(
    file: UploadFile = File(...),
    ground_truth: UploadFile | None = File(None),
) -> PDFSummaryResponse:
    """PDF 전체를 한 번의 모델 요청으로 추출·요약하고 평가 결과를 반환합니다."""

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
        # PDF 유효성과 페이지·표·이미지 진단 정보를 확인합니다.
        _, page_count, table_count, image_count = extract_text_from_pdf(
            file_bytes,
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="PDF 파일을 읽는 데 실패했습니다.",
        ) from error

    try:
        result = await asyncio.to_thread(analyze_pdf, file_bytes)
    except (httpx.HTTPError, ModelResponseError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"로컬 모델의 추출·요약 요청에 실패했습니다: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    text = result["extracted_text"]
    extraction_time_ms = round(
        (time.perf_counter() - extraction_started_at) * 1000,
        2,
    )

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF에서 텍스트를 추출하지 못했습니다.",
        )

    cer = None
    text_length_metrics = get_text_length_metrics(text)
    if ground_truth:
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
            ground_truth_text = ground_truth_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(
                status_code=400,
                detail="정답 텍스트 파일은 UTF-8 인코딩이어야 합니다.",
            ) from error

        cer = calculate_cer(ground_truth_text, text)
        text_length_metrics = get_text_length_metrics(text, ground_truth_text)

    return PDFSummaryResponse(
        filename=file.filename or "uploaded.pdf",
        model=ANALYSIS_MODEL_NAME,
        extraction_model=ANALYSIS_MODEL_NAME,
        extraction_method=ANALYSIS_MODEL_NAME,
        extraction_time_ms=extraction_time_ms,
        extracted_text=text,
        page_count=page_count,
        table_count=table_count,
        image_count=image_count,
        cer=cer,
        **text_length_metrics,
        keyword=result["keyword"],
        summary=result["summary"],
    )
