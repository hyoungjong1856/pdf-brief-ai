from typing import Literal

from pydantic import BaseModel


class PdfAnalysisContent(BaseModel):
    """AI 모델이 JSON으로 반환하는 3가지 항목입니다."""

    document: str = ""
    summary: str = ""
    keyword: str = ""


class PdfAnalysisResponse(BaseModel):
    """/ai/pdf 응답 형식입니다."""

    filename: str
    model: str
    extraction_model: str

    # "text"  : PyMuPDF로 내장 텍스트를 직접 추출
    # "image" : 페이지를 이미지로 렌더링해 OCR 모델에 전달
    extraction_method: Literal["text", "image"]
    extraction_time_ms: float

    page_count: int
    image_count: int
    drawing_count: int

    document: str
    summary: str
    keyword: str