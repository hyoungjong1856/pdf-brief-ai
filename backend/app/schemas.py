from pydantic import BaseModel


class PDFSummaryResponse(BaseModel):
    filename: str
    model: str
    extraction_model: str
    extraction_method: str
    extraction_time_ms: float
    extracted_text: str
    page_count: int
    table_count: int
    image_count: int
    keyword: str
    summary: str
