from pydantic import BaseModel


class PDFSummaryResponse(BaseModel):
    document_id: int | None = None
    summary_id: int | None = None
    created_at: str | None = None
    # 동일 파일(SHA-256 동일)이 이전에도 분석된 적이 있으면 True입니다.
    # force=False이고 ground_truth가 없으면 재분석 없이 저장된 요약을 그대로 돌려줍니다.
    existing: bool = False
    filename: str
    model: str
    extraction_model: str | None = None
    extraction_method: str
    extraction_time_ms: float
    extracted_text: str
    page_count: int
    cer: float | None = None
    extracted_text_length: int
    normalized_extracted_text_length: int
    normalized_ground_truth_text_length: int | None = None
    keyword: str
    summary: str

    # 하이브리드 경로 진단 정보입니다. vlm 경로에서는 기본값이 그대로 나갑니다.
    method: str = "hybrid"
    layout_source: str | None = None
    summary_model: str | None = None
    image_ocr_model: str | None = None
    image_region_count: int = 0
    ocr_region_count: int = 0
    orphan_block_count: int = 0
    scanned_page_count: int = 0
    layout_time_ms: float | None = None
    ocr_time_ms: float | None = None
    summary_time_ms: float | None = None
    warnings: list[str] = []