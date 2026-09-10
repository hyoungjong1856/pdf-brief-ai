import httpx

from fastapi import FastAPI, HTTPException

from app.ollama_service import ask_ollama, MODEL_NAME, check_ollama_alive
from app.schemas import ChatRequest, ChatResponse

from app.schemas import (
    ChatRequest,
    ChatResponse,
    SummaryRequest,
    SummaryResponse,
)
from app.ollama_service import (
    ask_ollama,
    MODEL_NAME,
    check_ollama_alive,
    summarize_text,
)


app = FastAPI(
    title="AIKOS Local AI API",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
    }


@app.get("/health/ai")
def health_ai() -> dict[str, str]:
    if check_ollama_alive():
        return {"status": "ok"}
    return {"status": "unavailable"}


@app.post(
    "/ai/chat",
    response_model=ChatResponse,
)
def chat(
    request: ChatRequest,
) -> ChatResponse:
    try:
        answer = ask_ollama(
            request.message
        )

    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Local AI provider request failed.",
        ) from error

    return ChatResponse(
        model=MODEL_NAME,
        answer=answer
    )


@app.post(
    "/ai/summary",
    response_model=SummaryResponse,
)
def summary(
    request: SummaryRequest,
) -> SummaryResponse:
    result = summarize_text(request.text)

    return SummaryResponse(
        summary=result
    )



#############################
# PDF 작업을 위한 추가 사항
#############################

from io import BytesIO
from fastapi import UploadFile, File
from pypdf import PdfReader
from app.schemas import PDFSummaryResponse
from app.ollama_service import extract_keywords_and_summary


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)
    return "\n".join(text_parts)


@app.post(
    "/ai/pdf",
    response_model=PDFSummaryResponse,
)
async def pdf_summary(
    file: UploadFile = File(...),
) -> PDFSummaryResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="PDF 파일만 업로드할 수 있습니다.",
        )

    file_bytes = await file.read()

    try:
        text = extract_text_from_pdf(file_bytes)
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="PDF 텍스트 추출에 실패했습니다.",
        ) from error

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF에서 텍스트를 찾을 수 없습니다. (스캔 이미지 PDF일 수 있습니다)",
        )

    try:
        result = extract_keywords_and_summary(text)
    except httpx.HTTPError as error:
        raise HTTPException(
        status_code=502,
        detail="Local AI provider request failed.",
        ) from error

    return PDFSummaryResponse(
    filename=file.filename,
    model=MODEL_NAME,
    keyword=result["keyword"],
    summary=result["summary"],
)