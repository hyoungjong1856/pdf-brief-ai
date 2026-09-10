from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=2000,
    )


class ChatResponse(BaseModel):
    model: str
    answer: str


class SummaryRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=5000,
    )


class SummaryResponse(BaseModel):
    summary: str


#############################
# PDF 작업을 위한 추가 사항
#############################

class PDFSummaryResponse(BaseModel):
    filename: str
    model: str
    keyword: str
    summary: str