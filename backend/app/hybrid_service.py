"""레이아웃 순서에 맞춰 본문 텍스트와 이미지 OCR 결과를 하나로 엮습니다.

처리 순서는 다음과 같습니다.

1. 레이아웃 판단으로 페이지의 영역과 읽기 순서를 얻습니다.
2. 텍스트·표 영역은 PyMuPDF로 원문을 그대로 꺼냅니다. 텍스트 레이어가 있는 PDF에서는
   OCR보다 빠르고 정확합니다.
3. 이미지 영역만 잘라내 PaddleOCR-VL에 보냅니다.
4. 두 결과를 읽기 순서대로 합칩니다. 이미지를 맨 뒤에 몰아 붙이면 글자 수는 같아도
   문맥이 끊겨 요약 품질이 무너지므로, 반드시 원래 위치에 끼워 넣습니다.
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass, field

import pymupdf
from PIL import Image

from app.image_ocr import ImageOcrError, ocr_image
from app.layout import IMAGE, TABLE, TEXT, Region, build_page_layout, paddle_status

logger = logging.getLogger(__name__)

# 이미지 영역을 잘라 OCR에 보낼 때의 해상도. 너무 낮으면 작은 글자가 뭉개집니다.
OCR_DPI = int(os.getenv("OCR_DPI") or 200)
# 페이지에 텍스트가 전혀 없으면 텍스트 레이어가 없는 스캔본으로 간주합니다.
# 몇 글자 이상을 "충분한" 텍스트로 볼지는 근거 없는 임의의 기준이 되기 쉬우므로,
# 공백을 제거하고 한 글자라도 남으면 텍스트 레이어가 있는 것으로 판단합니다.
# OCR에 보낼 이미지의 긴 변 최대 픽셀 수. 텍스트 레이어가 없는 스캔 페이지는 전체를
# 이미지 한 장으로 보내는데, 페이지 전체 크기 그대로 보내면 비전 인코더가 만드는
# 이미지 토큰 수가 지나치게 많아져 컨텍스트를 넘기거나(모델이 400으로 거부) 처리 시간이
# 과도하게 늘어납니다. 작은 그림·표 영역은 원래 이 크기보다 작아 사실상 영향이 없습니다.
MAX_OCR_IMAGE_PX = int(os.getenv("MAX_OCR_IMAGE_PX") or 2000)


@dataclass
class ExtractionResult:
    """하이브리드 추출 결과와 진단 정보."""

    text: str
    page_count: int
    image_region_count: int
    ocr_region_count: int
    orphan_block_count: int
    scanned_page_count: int
    layout_source: str
    warnings: list[str] = field(default_factory=list)
    layout_time_ms: float = 0.0
    ocr_time_ms: float = 0.0


def _render_region(page: pymupdf.Page, region: Region) -> bytes:
    """영역만 잘라 PNG로 렌더링합니다.

    PyMuPDF가 clip을 PDF 좌표로 받아 직접 잘라주므로 픽셀 좌표를 따로 계산할 필요가 없습니다.
    """

    rect = region.rect & page.rect
    if rect.is_empty:
        rect = page.rect
    pixmap = page.get_pixmap(clip=rect, dpi=OCR_DPI, alpha=False)
    return _cap_image_size(pixmap.tobytes("png"))


def _cap_image_size(png_bytes: bytes) -> bytes:
    """긴 변이 MAX_OCR_IMAGE_PX를 넘으면 비율을 유지한 채 줄입니다."""

    with Image.open(io.BytesIO(png_bytes)) as image:
        long_edge = max(image.size)
        if long_edge <= MAX_OCR_IMAGE_PX:
            return png_bytes

        scale = MAX_OCR_IMAGE_PX / long_edge
        new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        resized = image.convert("RGB").resize(new_size, Image.LANCZOS)

        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        return buffer.getvalue()


# 벡터 그래픽 그림(차트 축 눈금, 패널 문자 A1/B1 등)은 래스터 이미지가 아니라 PDF 안에
# 진짜 텍스트로 심어져 있어서 OCR 대상으로 걸리지 않고 일반 텍스트 블록으로 뽑힙니다.
# 그 결과 본문 문단 사이에 "A1 B1 A2 B2..." 같은 조각이 끼어드는 문제가 생깁니다.
# 문장 부호로 끝나지 않는 매우 짧은 조각이 연속으로 나오면 그림 부속물로 보고 제외합니다.
_LABEL_LIKE_MAX_CHARS = 24
_LABEL_RUN_MIN = 3


def _looks_like_figure_label(text: str) -> bool:
    """짧고 문장 부호로 끝나지 않는 조각을 그림 라벨(축 눈금, 패널 문자 등) 후보로 봅니다."""

    stripped = text.strip()
    if not stripped or len(stripped) > _LABEL_LIKE_MAX_CHARS:
        return False
    if stripped[-1] in ".!?":
        return False
    return len(stripped.split()) <= 4


def _strip_figure_furniture(parts: list[str], warnings: list[str], page_index: int) -> list[str]:
    """짧은 조각이 연속으로 몰려 있으면 본문 흐름에서 분리해 페이지 끝에 모아 둡니다.

    지우지 않고 옮기기만 하는 이유는, "짧고 문장 부호 없는 조각의 연속"이라는
    신호가 그림 라벨뿐 아니라 표가 제대로 인식되지 않았을 때의 표 셀 값이나
    짧은 목록 항목에서도 나타날 수 있기 때문입니다. 오판하더라도 정보를 잃지
    않고 순서만 밀리는 정도로 피해를 제한합니다.
    """

    cleaned: list[str] = []
    furniture: list[str] = []
    index = 0
    while index < len(parts):
        if _looks_like_figure_label(parts[index]):
            run_end = index
            while run_end < len(parts) and _looks_like_figure_label(parts[run_end]):
                run_end += 1
            run_length = run_end - index
            if run_length >= _LABEL_RUN_MIN:
                furniture.extend(parts[index:run_end])
                index = run_end
                continue
        cleaned.append(parts[index])
        index += 1

    if furniture:
        warnings.append(
            f"{page_index}쪽: 그림 라벨로 보이는 짧은 텍스트 {len(furniture)}개를 "
            "본문 흐름에서 분리해 페이지 끝에 모았습니다(삭제하지 않음)."
        )
        cleaned.append("[그림/표 라벨로 추정되는 텍스트] " + " · ".join(furniture))

    return cleaned


def extract_image_document(png_bytes: bytes) -> ExtractionResult:
    """이미지 파일 한 장을 PDF 변환 없이 바로 OCR합니다.

    PDF 경로의 "텍스트 레이어가 없는 페이지는 전면 OCR" 분기와 결과적으로
    같은 일을 하지만, 이미지는 원래부터 레이아웃 판단 대상이 아니므로
    pymupdf로 PDF를 만들고 다시 여는 과정 없이 곧바로 처리합니다.
    """

    warnings: list[str] = ["이미지 파일은 PDF 변환 없이 전면 OCR로 직접 처리했습니다."]

    started = time.perf_counter()
    try:
        text = ocr_image(_cap_image_size(png_bytes), hint="업로드된 이미지")
    finally:
        ocr_time_ms = (time.perf_counter() - started) * 1000

    return ExtractionResult(
        text=text.strip(),
        page_count=1,
        image_region_count=1,
        ocr_region_count=1,
        orphan_block_count=0,
        scanned_page_count=1,
        layout_source="image(direct, 레이아웃 판단 없음)",
        warnings=warnings,
        layout_time_ms=0.0,
        ocr_time_ms=round(ocr_time_ms, 2),
    )


def extract_document(file_bytes: bytes) -> ExtractionResult:
    """PDF 전체를 읽기 순서대로 추출합니다."""

    parts: list[str] = []
    warnings: list[str] = []
    image_region_count = 0
    ocr_region_count = 0
    orphan_block_count = 0
    scanned_page_count = 0
    paddle_pages = 0
    layout_time_ms = 0.0
    ocr_time_ms = 0.0

    with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
        page_count = document.page_count

        for page_index, page in enumerate(document, start=1):
            page_text = (page.get_text("text") or "").strip()

            # 텍스트 레이어가 없는 페이지는 영역을 나눌 근거가 없으므로
            # 페이지 전체를 이미지 한 장으로 보고 OCR에 맡깁니다.
            if not page_text:
                scanned_page_count += 1
                regions = [
                    Region(
                        bbox=(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1),
                        kind=IMAGE,
                        label="full-page",
                        source="scanned",
                    )
                ]
                warnings.append(f"{page_index}쪽은 텍스트 레이어가 없어 전면 OCR로 처리했습니다.")
            else:
                started = time.perf_counter()
                layout = build_page_layout(page)
                layout_time_ms += (time.perf_counter() - started) * 1000

                regions = layout.regions
                orphan_block_count += layout.orphan_count
                if layout.paddle_used:
                    paddle_pages += 1
                warnings.extend(f"{page_index}쪽: {w}" for w in layout.warnings)

            page_parts: list[str] = []
            for region in regions:
                if region.kind == IMAGE:
                    image_region_count += 1
                    started = time.perf_counter()
                    try:
                        text = ocr_image(
                            _render_region(page, region),
                            hint=f"{page_index}쪽 이미지 영역",
                        )
                    finally:
                        ocr_time_ms += (time.perf_counter() - started) * 1000
                    ocr_region_count += 1
                    page_parts.append(text)
                    continue

                if region.kind in (TEXT, TABLE):
                    text = page.get_text("text", clip=region.rect, sort=True) or ""
                    text = text.strip()
                    if text:
                        page_parts.append(text)

            if page_parts:
                page_parts = _strip_figure_furniture(page_parts, warnings, page_index)
            if page_parts:
                parts.append("\n\n".join(page_parts))

    if paddle_pages:
        layout_source = f"{paddle_status()} + pymupdf(cross-check)"
    else:
        layout_source = "pymupdf(geometric)"

    return ExtractionResult(
        text="\n\n".join(parts).strip(),
        page_count=page_count,
        image_region_count=image_region_count,
        ocr_region_count=ocr_region_count,
        orphan_block_count=orphan_block_count,
        scanned_page_count=scanned_page_count,
        layout_source=layout_source,
        warnings=warnings,
        layout_time_ms=round(layout_time_ms, 2),
        ocr_time_ms=round(ocr_time_ms, 2),
    )


__all__ = ["ExtractionResult", "ImageOcrError", "extract_document", "extract_image_document"]