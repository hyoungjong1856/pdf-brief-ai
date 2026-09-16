from pydantic import BaseModel


class PDFSummaryResponse(BaseModel):
    document_id: int | None = None
    summary_id: int | None = None
    created_at: str | None = None
    existing: bool = False
    filename: str
    model: str
    extraction_model: str
    extraction_method: str
    extraction_time_ms: float
    extracted_text: str
    page_count: int
    table_count: int
    image_count: int
    cer: float | None = None
    extracted_text_length: int
    normalized_extracted_text_length: int
    normalized_ground_truth_text_length: int | None = None
    keyword: str
    summary: str
