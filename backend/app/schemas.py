from pydantic import BaseModel


class PDFSummaryResponse(BaseModel):
    filename: str
    model: str
    keyword: str
    summary: str
