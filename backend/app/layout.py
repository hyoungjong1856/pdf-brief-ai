"""PDF 페이지의 레이아웃 영역과 읽기 순서를 판단합니다.

두 가지 출처를 함께 사용하고 교차 검증합니다.

- PaddleOCR PP-DocLayoutV2: 페이지 이미지에서 영역을 검출·분류하고 읽기 순서를
  예측합니다. RT-DETR 검출기 뒤에 포인터 네트워크가 붙어 있어 "순서 판단"이 강점이지만,
  좌표는 어디까지나 예측값이라 오차가 있고 영역을 통째로 놓칠 수도 있습니다.
- PyMuPDF: PDF 콘텐츠 스트림에서 블록·이미지 좌표를 직접 읽습니다. "좌표와 존재 여부"는
  추론이 아니라 사실이므로 정답으로 취급합니다. 대신 읽기 순서는 기하 휴리스틱이라 약합니다.

따라서 순서는 PaddleOCR을, 좌표와 누락 검증은 PyMuPDF를 신뢰하는 방식으로 융합합니다.
PaddleOCR이 설치되지 않은 환경에서는 PyMuPDF 단독 기하 판단으로 자동 강등됩니다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import pymupdf

logger = logging.getLogger(__name__)

# 영역 종류. DROP은 본문에서 제외할 머리말·꼬리말·페이지 번호입니다.
TEXT = "text"
IMAGE = "image"
TABLE = "table"
DROP = "drop"

LAYOUT_DPI = int(os.getenv("LAYOUT_DPI") or 150)
PADDLE_LAYOUT_MODEL = os.getenv("PADDLE_LAYOUT_MODEL") or "PP-DocLayoutV2"

# PaddleOCR 레이아웃 라벨을 내부 종류로 매핑합니다.
# PP-DocLayout 계열은 20~23개 라벨을 내보내므로 대표 표기를 모두 받아둡니다.
_LABEL_KIND = {
    "text": TEXT,
    "paragraph_title": TEXT,
    "doc_title": TEXT,
    "document_title": TEXT,
    "title": TEXT,
    "abstract": TEXT,
    "content": TEXT,
    "reference": TEXT,
    "references": TEXT,
    "algorithm": TEXT,
    "formula": TEXT,
    "formula_number": TEXT,
    "figure_title": TEXT,
    "figure_caption": TEXT,
    "table_title": TEXT,
    "table_caption": TEXT,
    "chart_title": TEXT,
    "aside_text": TEXT,
    "footnote": TEXT,
    "table": TABLE,
    "image": IMAGE,
    "figure": IMAGE,
    "chart": IMAGE,
    "seal": IMAGE,
    "header": DROP,
    "footer": DROP,
    "header_image": DROP,
    "footer_image": DROP,
    "page_number": DROP,
    "number": DROP,
}

# 융합 과정에서 쓰는 허용 오차(PDF 포인트). PaddleOCR bbox가 몇 포인트 어긋나도
# 같은 영역으로 인정하기 위한 값입니다.
_SNAP_TOLERANCE = 6.0
# 컬럼 사이 여백(gutter)으로 인정할 최소 폭.
_MIN_GUTTER_PT = 12.0
# 가로 띠를 가를 최소 여백. 문단 사이 간격보다 커야 본문이 잘못 쪼개지지 않습니다.
_MIN_BAND_GAP_PT = 14.0
# 전폭으로 간주할 최소 가로 비율. 표의 행이나 제목처럼 폭 대부분을 차지하는 요소는
# 재귀 분할에 그대로 섞이면 좌우 간격 탐지 자체를 가려버립니다(아래 _split_full_width_rows).
_FULL_WIDTH_RATIO = 0.78
# 컬럼 순서를 못 정하고 평면 정렬로 떨어졌을 때, 경고를 남길 최소 영역 개수.
_UNRESOLVED_WARNING_MIN_REGIONS = 3


@dataclass
class Region:
    """읽기 순서가 매겨진 레이아웃 영역 하나."""

    bbox: tuple[float, float, float, float]
    kind: str
    label: str = ""
    source: str = "pymupdf"
    paddle_order: int | None = None

    @property
    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(*self.bbox)


@dataclass
class PageLayout:
    """한 페이지의 최종 영역 목록과 교차 검증 결과."""

    regions: list[Region] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    paddle_used: bool = False
    orphan_count: int = 0
    order_conflicts: int = 0


# --------------------------------------------------------------------------- #
# PyMuPDF 측: 콘텐츠 스트림에서 직접 읽는 정확한 좌표
# --------------------------------------------------------------------------- #


def _text_blocks(page: pymupdf.Page) -> list[Region]:
    """페이지의 텍스트 블록을 좌표와 함께 반환합니다."""

    regions: list[Region] = []
    for block in page.get_text("blocks"):
        # (x0, y0, x1, y1, text, block_no, block_type) 형태이며 block_type 0이 텍스트입니다.
        # 다른 타입이 섞여 들어와도 죽지 않도록 길이와 자료형을 먼저 확인합니다.
        if len(block) < 7 or block[6] != 0:
            continue
        if not isinstance(block[4], str) or not block[4].strip():
            continue
        regions.append(
            Region(bbox=tuple(float(v) for v in block[:4]), kind=TEXT, source="pymupdf")
        )
    return regions


def _image_rects(page: pymupdf.Page) -> list[Region]:
    """페이지에 실제로 배치된 이미지의 좌표를 반환합니다.

    PaddleOCR의 image 라벨과 달리 이 목록은 추론이 아니라 확정된 사실이므로,
    "어떤 이미지를 OCR에 보낼지"는 항상 이 결과를 기준으로 결정합니다.
    """

    regions: list[Region] = []
    seen: set[tuple[int, int, int, int]] = set()

    for image in page.get_images(full=True):
        xref = image[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:  # noqa: BLE001 - 손상된 xref가 페이지 전체를 막지 않도록 합니다.
            logger.warning("이미지 xref %s의 좌표를 읽지 못했습니다.", xref)
            continue

        for rect in rects:
            # 아이콘·구분선 수준의 장식 이미지는 OCR 대상에서 제외합니다.
            if rect.width < 24 or rect.height < 24:
                continue
            key = (int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1))
            if key in seen:
                continue
            seen.add(key)
            regions.append(
                Region(
                    bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                    kind=IMAGE,
                    label=f"xref:{xref}",
                    source="pymupdf",
                )
            )
    return regions


# 이 정도 길이 이상의 실제 텍스트가 이미지 영역 안에서 뽑히면, 그 이미지는 "OCR이
# 필요한 그림"이 아니라 실제 텍스트 위(또는 아래)에 깔린 배경/워터마크 이미지로 봅니다.
# 원본 보존용으로 페이지 스캔 이미지를 함께 넣어두는 PDF에서 흔한 패턴입니다.
_TEXT_BACKED_IMAGE_MIN_CHARS = 15


def _skip_text_backed_images(
    page: pymupdf.Page, image_regions: list[Region]
) -> tuple[list[Region], int]:
    """같은 자리에 이미 뽑을 수 있는 실제 텍스트가 있는 이미지는 OCR 대상에서 뺍니다.

    이런 이미지를 그대로 OCR에 보내면 두 가지 문제가 생깁니다: 이미 공짜로 정확하게
    있는 원문 옆에 부정확할 수 있는 OCR 결과가 중복으로 섞이고, 불필요한 OCR 요청으로
    시간이 낭비됩니다. 진짜 그림(사진·차트)은 그 자리에 추출 가능한 텍스트가 없으므로
    이 검사에 걸리지 않고 정상적으로 OCR됩니다.
    """

    kept: list[Region] = []
    skipped = 0
    for region in image_regions:
        text = (page.get_text("text", clip=region.rect) or "").strip()
        if len(text) >= _TEXT_BACKED_IMAGE_MIN_CHARS:
            skipped += 1
            continue
        kept.append(region)
    return kept, skipped


# --------------------------------------------------------------------------- #
# 기하 기반 읽기 순서 (PyMuPDF 단독 경로이자 융합 시 보간 기준)
# --------------------------------------------------------------------------- #


def _gaps(spans: list[tuple[float, float]], lo: float, hi: float, minimum: float):
    """구간 목록을 lo~hi에 투영해 어디에도 덮이지 않는 여백을 찾습니다."""

    merged: list[list[float]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    gaps = []
    for left, right in zip(merged, merged[1:]):
        if right[0] - left[1] >= minimum:
            gaps.append((left[1], right[0]))
    return gaps


def _looks_tabular(left: list[Region], right: list[Region]) -> bool:
    """세로 분할 후보가 컬럼이 아니라 표의 셀 경계인지 판별합니다.

    표는 같은 행의 셀끼리 y 범위가 거의 일치합니다. 반면 진짜 다단은 좌우 단의
    줄바꿈 위치가 제각각이라 그런 쌍이 드뭅니다. 이 차이로 구분합니다.
    """

    if not left or not right:
        return False

    paired = 0
    for a in left:
        for b in right:
            if abs(a.bbox[1] - b.bbox[1]) < 3 and abs(a.bbox[3] - b.bbox[3]) < 3:
                paired += 1
                break
    return paired / len(left) > 0.5


def _vertical_cut(regions: list[Region]):
    """어떤 영역도 가로지르지 않는 세로 여백에서 좌우로 나눕니다."""

    if len(regions) < 2:
        return None

    x0 = min(r.bbox[0] for r in regions)
    x1 = max(r.bbox[2] for r in regions)
    gaps = _gaps([(r.bbox[0], r.bbox[2]) for r in regions], x0, x1, _MIN_GUTTER_PT)
    if not gaps:
        return None

    # 가장 넓은 여백을 컬럼 경계 후보로 봅니다.
    start, end = max(gaps, key=lambda g: g[1] - g[0])
    gutter = (start + end) / 2

    left = [r for r in regions if r.bbox[2] <= gutter]
    right = [r for r in regions if r.bbox[0] >= gutter]
    if not left or not right or len(left) + len(right) != len(regions):
        return None
    if _looks_tabular(left, right):
        return None
    return left, right


def _horizontal_cut(regions: list[Region]):
    """가로로 비어 있는 여백에서 위아래로 나눕니다."""

    if len(regions) < 2:
        return None

    y0 = min(r.bbox[1] for r in regions)
    y1 = max(r.bbox[3] for r in regions)
    gaps = _gaps([(r.bbox[1], r.bbox[3]) for r in regions], y0, y1, _MIN_BAND_GAP_PT)
    if not gaps:
        return None

    start, end = max(gaps, key=lambda g: g[1] - g[0])
    split = (start + end) / 2

    top = [r for r in regions if r.bbox[3] <= split]
    bottom = [r for r in regions if r.bbox[1] >= split]
    if not top or not bottom or len(top) + len(bottom) != len(regions):
        return None
    return top, bottom


def _split_full_width_rows(regions: list[Region]):
    """전폭에 가까운 영역을 재귀 분할 전에 먼저 '행'으로 떼어냅니다.

    표의 각 행이나 폭 대부분을 차지하는 제목·꼬리말은 좌우 컬럼 사이 여백을
    통째로 덮어버려, XY-cut이 세로 여백도 가로 여백도 찾지 못하고 완전히
    무관한 본문까지 한꺼번에 평면 정렬로 떨어지게 만드는 원인이 됩니다.
    이런 요소는 애초에 컬럼 판단 대상에서 빼고 y순서대로 그 자체를 하나의
    '행'으로 확정해 버리면, 남은 컬럼 텍스트만으로 간격 탐지가 안정적으로 동작합니다.

    반환값은 [("row", Region), ...] 또는 [("segment", [Region, ...]), ...]로 이뤄진,
    y순서를 따르는 항목 목록입니다.
    """

    if not regions:
        return []

    x0 = min(r.bbox[0] for r in regions)
    x1 = max(r.bbox[2] for r in regions)
    threshold = (x1 - x0) * _FULL_WIDTH_RATIO

    items: list[tuple[str, Region | list[Region]]] = []
    segment: list[Region] = []

    for region in sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0])):
        if (region.bbox[2] - region.bbox[0]) >= threshold:
            if segment:
                items.append(("segment", segment))
                segment = []
            items.append(("row", region))
        else:
            segment.append(region)

    if segment:
        items.append(("segment", segment))
    return items


def _xy_cut(
    regions: list[Region], depth: int = 0, warnings: list[str] | None = None
) -> list[Region]:
    """재귀 XY-cut으로 읽기 순서를 정합니다.

    세로 분할(컬럼)을 먼저 시도합니다. 어떤 영역도 가로지르지 않는 세로 여백은
    다단 구조의 강한 신호인 반면, 가로 여백은 문단 사이에서도 흔히 생기기 때문입니다.
    """

    if len(regions) <= 1 or depth > 12:
        return sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0]))

    cut = _vertical_cut(regions)
    if cut is not None:
        return _xy_cut(cut[0], depth + 1, warnings) + _xy_cut(cut[1], depth + 1, warnings)

    cut = _horizontal_cut(regions)
    if cut is not None:
        return _xy_cut(cut[0], depth + 1, warnings) + _xy_cut(cut[1], depth + 1, warnings)

    # 세로로도 가로로도 나누지 못했습니다. 정말 컬럼이 섞여 있는 채로 여기까지
    # 왔다면(개수가 많고 x 시작 위치가 서로 크게 퍼져 있다면) 순서 품질을 신뢰할 수
    # 없다는 신호이므로, 원인 파악에 쓸 수 있도록 기록해 둡니다.
    if warnings is not None and len(regions) >= _UNRESOLVED_WARNING_MIN_REGIONS:
        x_starts = sorted(r.bbox[0] for r in regions)
        if x_starts[-1] - x_starts[0] > 100:
            warnings.append(
                f"영역 {len(regions)}개의 컬럼 순서를 확정하지 못해 "
                "근사 정렬(위→아래, 왼쪽→오른쪽)로 처리했습니다."
            )

    return sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0]))


def geometric_order(
    regions: list[Region], page=None, warnings: list[str] | None = None
) -> list[Region]:
    """영역을 사람이 읽는 순서대로 정렬합니다.

    먼저 전폭 요소(제목, 표의 행, 꼬리말 등)를 골라내 확정된 순서로 배치하고,
    그 사이에 낀 컬럼 텍스트 구간에만 재귀 XY-cut을 적용합니다. 전폭 요소를
    재귀 분할과 같은 층위에서 함께 다루면, 폭 넓은 bbox 하나가 좌우 간격 탐지
    자체를 가려서 전혀 무관한 본문까지 통째로 순서가 무너질 수 있습니다.
    """

    if not regions:
        return []

    ordered: list[Region] = []
    for kind, payload in _split_full_width_rows(regions):
        if kind == "row":
            ordered.append(payload)  # type: ignore[arg-type]
        else:
            ordered.extend(_xy_cut(payload, warnings=warnings))  # type: ignore[arg-type]
    return ordered


# --------------------------------------------------------------------------- #
# PaddleOCR 측: 학습된 읽기 순서 판단
# --------------------------------------------------------------------------- #


class _PaddleLayout:
    """PP-DocLayoutV2 모델을 지연 로딩해 재사용합니다."""

    def __init__(self) -> None:
        self._model = None
        self._unavailable_reason: str | None = None

    def available(self) -> bool:
        return self._load() is not None

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    def _load(self):
        if self._model is not None or self._unavailable_reason is not None:
            return self._model

        try:
            from paddleocr import LayoutDetection
        except Exception as error:  # noqa: BLE001 - 설치 여부와 무관하게 서버는 떠야 합니다.
            self._unavailable_reason = f"paddleocr를 불러오지 못했습니다: {error}"
            logger.info("PaddleOCR 레이아웃 비활성화 — %s", self._unavailable_reason)
            return None

        try:
            self._model = LayoutDetection(model_name=PADDLE_LAYOUT_MODEL)
        except Exception as error:  # noqa: BLE001
            self._unavailable_reason = (
                f"레이아웃 모델 {PADDLE_LAYOUT_MODEL} 초기화에 실패했습니다: {error}"
            )
            logger.warning("PaddleOCR 레이아웃 비활성화 — %s", self._unavailable_reason)
            return None

        logger.info("PaddleOCR 레이아웃 모델 %s 로드 완료", PADDLE_LAYOUT_MODEL)
        return self._model

    def detect(self, page: pymupdf.Page) -> list[Region]:
        """페이지를 렌더링해 영역을 검출하고 PDF 좌표계로 되돌립니다."""

        model = self._load()
        if model is None:
            return []

        import numpy as np
        from PIL import Image

        scale = LAYOUT_DPI / 72.0
        pixmap = page.get_pixmap(dpi=LAYOUT_DPI, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

        try:
            outputs = model.predict(np.array(image), batch_size=1)
        except Exception as error:  # noqa: BLE001
            logger.warning("레이아웃 검출에 실패했습니다: %s", error)
            return []

        regions: list[Region] = []
        for output in outputs:
            for order, box in enumerate(_iter_boxes(output)):
                coordinate = box.get("coordinate") or box.get("bbox")
                if not coordinate or len(coordinate) < 4:
                    continue

                label = str(box.get("label") or box.get("cls_name") or "").lower()
                kind = _LABEL_KIND.get(label.replace(" ", "_"), TEXT)

                # 모델이 명시적 순서를 주면 그것을, 아니면 출력 순서를 씁니다.
                raw_order = box.get("order")
                if raw_order is None:
                    raw_order = box.get("index")
                paddle_order = int(raw_order) if raw_order is not None else order

                # 픽셀 좌표를 PDF 포인트로 되돌립니다. 이 변환을 빼먹으면 영역이 전부 어긋납니다.
                regions.append(
                    Region(
                        bbox=(
                            float(coordinate[0]) / scale,
                            float(coordinate[1]) / scale,
                            float(coordinate[2]) / scale,
                            float(coordinate[3]) / scale,
                        ),
                        kind=kind,
                        label=label,
                        source="paddle",
                        paddle_order=paddle_order,
                    )
                )

        regions.sort(key=lambda r: r.paddle_order if r.paddle_order is not None else 0)
        return regions


def _iter_boxes(output) -> list[dict]:
    """PaddleOCR 결과 객체에서 박스 목록을 방어적으로 꺼냅니다.

    버전에 따라 결과 스키마가 달라 여러 경로를 순서대로 시도합니다.
    """

    for getter in (
        lambda: output["boxes"],
        lambda: output.json["res"]["boxes"],
        lambda: output["res"]["boxes"],
    ):
        try:
            boxes = getter()
        except Exception:  # noqa: BLE001
            continue
        if isinstance(boxes, list):
            return [b for b in boxes if isinstance(b, dict)]
    logger.warning("레이아웃 결과에서 박스 목록을 찾지 못했습니다.")
    return []


_paddle_layout = _PaddleLayout()


def paddle_available() -> bool:
    return _paddle_layout.available()


def paddle_status() -> str:
    if _paddle_layout.available():
        return PADDLE_LAYOUT_MODEL
    return f"unavailable ({_paddle_layout.unavailable_reason})"


# --------------------------------------------------------------------------- #
# 교차 검증 융합
# --------------------------------------------------------------------------- #


def _contains(outer: tuple[float, ...], inner: tuple[float, ...]) -> bool:
    """inner의 중심이 outer 안에 있는지 확인합니다."""

    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return (
        outer[0] - _SNAP_TOLERANCE <= cx <= outer[2] + _SNAP_TOLERANCE
        and outer[1] - _SNAP_TOLERANCE <= cy <= outer[3] + _SNAP_TOLERANCE
    )


def _union(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _count_inversions(values: list[int]) -> int:
    """기하 순서와 모델 순서가 얼마나 어긋나는지 세는 역전 쌍 개수입니다."""

    inversions = 0
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] > values[j]:
                inversions += 1
    return inversions


# 두 영역이 이 비율 이상 겹쳐야 "같은 내용에 중복 예측된 박스"로 봅니다. 일반 문서에서
# 서로 다른 문단이 이 정도로 겹치는 일은 거의 없으므로, 오판을 줄이려 다소 높게 잡았습니다.
_OVERLAP_DUP_RATIO = 0.75


def _overlap_ratio(a: Region, b: Region) -> float:
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-6, (bx1 - bx0) * (by1 - by0))
    return intersection / min(area_a, area_b)


def _dedupe_overlaps(regions: list[Region], warnings: list[str] | None = None) -> list[Region]:
    """같은 종류의 영역이 크게 겹치면(모델이 같은 내용에 박스를 두 개 예측한 경우)
    하나로 합칩니다.

    반드시 "같은 종류"끼리만, 그리고 겹치는 두 bbox를 합집합으로 "병합"하지
    "삭제"하지 않습니다. 겹친다고 무조건 한쪽을 버리면, bbox 예측이 살짝
    부정확해서 큰 영역이 실제로는 다른 내용인 작은 문단을 덮어버린 경우
    그 문단이 통째로 사라지는 위험이 있습니다. 합집합 병합은 내용을 잃지
    않으면서 같은 구간이 두 번 추출되는 것만 막습니다.

    TEXT와 IMAGE처럼 서로 다른 종류가 겹치는 것은 건드리지 않습니다 — 그림과
    캡션이 맞닿아 겹쳐 보이는 것은 정상적인 레이아웃이라, 여기서 지우면
    더 위험합니다. 이미지 영역에 실제로 원문 텍스트가 있는 경우는 이 함수
    이전 단계(_skip_text_backed_images)에서 이미 걸러집니다.
    """

    kept: list[Region] = []
    merged_count = 0
    # 넓은 영역부터 처리해야 작은 조각이 이미 자리 잡은 큰 영역에 합쳐집니다.
    ordered = sorted(
        regions,
        key=lambda r: (r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]),
        reverse=True,
    )

    for region in ordered:
        collision = next(
            (
                existing
                for existing in kept
                if existing.kind == region.kind
                and _overlap_ratio(region, existing) >= _OVERLAP_DUP_RATIO
            ),
            None,
        )

        if collision is None:
            kept.append(region)
            continue

        # 삭제 대신 병합: 두 bbox를 합쳐 어느 쪽 내용도 잃지 않습니다.
        collision.bbox = _union(collision.bbox, region.bbox)
        merged_count += 1

    if merged_count and warnings is not None:
        warnings.append(f"같은 내용에 중복 예측된 영역 {merged_count}개를 하나로 병합했습니다.")

    return kept


def build_page_layout(page: pymupdf.Page) -> PageLayout:
    """한 페이지의 최종 영역 목록을 만듭니다."""

    layout = PageLayout()

    text_blocks = _text_blocks(page)
    image_regions = _image_rects(page)
    image_regions, text_backed_count = _skip_text_backed_images(page, image_regions)
    if text_backed_count:
        layout.warnings.append(
            f"이미지 영역 {text_backed_count}개는 같은 자리에 원문 텍스트가 이미 있어 "
            "OCR을 건너뛰었습니다."
        )
    paddle_regions = _paddle_layout.detect(page)

    # PaddleOCR을 쓸 수 없으면 PyMuPDF 기하 판단 단독으로 처리합니다.
    if not paddle_regions:
        if _paddle_layout.unavailable_reason:
            layout.warnings.append(
                "PaddleOCR 레이아웃을 쓸 수 없어 PyMuPDF 기하 판단으로 처리했습니다."
            )
        else:
            layout.warnings.append("레이아웃 검출 결과가 비어 PyMuPDF 기하 판단으로 처리했습니다.")
        deduped = _dedupe_overlaps(text_blocks + image_regions, warnings=layout.warnings)
        layout.regions = geometric_order(deduped, page, warnings=layout.warnings)
        return layout

    layout.paddle_used = True

    # ① 이미지 영역의 권한은 PyMuPDF에 둡니다.
    #    PaddleOCR의 image 계열 영역은 순서 참고용으로만 남기고 실제 대상에서는 제외합니다.
    paddle_text_regions = [r for r in paddle_regions if r.kind in (TEXT, TABLE)]
    paddle_image_regions = [r for r in paddle_regions if r.kind == IMAGE]

    # ② bbox 스냅: 예측 좌표를 그 안에 들어오는 실제 텍스트 블록 경계로 넓혀 보정합니다.
    matched: set[int] = set()
    for region in paddle_text_regions:
        snapped = region.bbox
        for index, block in enumerate(text_blocks):
            if _contains(region.bbox, block.bbox):
                matched.add(index)
                snapped = _union(snapped, block.bbox)
        region.bbox = snapped
        region.source = "fused"

    # ③ 고아 텍스트 탐지: 어떤 영역에도 걸리지 않은 블록은 모델이 놓친 것입니다.
    orphans = [block for index, block in enumerate(text_blocks) if index not in matched]
    layout.orphan_count = len(orphans)
    if orphans:
        layout.warnings.append(
            f"레이아웃이 놓친 텍스트 블록 {len(orphans)}개를 기하 순서로 보정해 삽입했습니다."
        )

    # ④ 이미지는 PyMuPDF 좌표를 쓰되, 순서는 겹치는 PaddleOCR 영역의 순서를 물려받습니다.
    for image_region in image_regions:
        best: Region | None = None
        for candidate in paddle_image_regions:
            if _contains(candidate.bbox, image_region.bbox) or _contains(
                image_region.bbox, candidate.bbox
            ):
                best = candidate
                break
        if best is not None:
            image_region.paddle_order = best.paddle_order
            image_region.source = "fused"
        else:
            layout.warnings.append(
                "레이아웃이 검출하지 못한 이미지를 기하 위치로 삽입했습니다."
            )

    # ④-1 겹침 정리: PaddleOCR 박스 중복 예측이나, 텍스트를 이미지로 잘못 분류해
    #      OCR과 원문 추출이 같은 자리에서 동시에 일어나는 경우를 걸러냅니다.
    #      순서(paddle_order)를 지닌 영역을 우선 유지하도록 먼저 채택합니다.
    combined = sorted(
        paddle_text_regions + image_regions + orphans,
        key=lambda r: (r.paddle_order is None, r.paddle_order if r.paddle_order is not None else 0),
    )
    final_regions = _dedupe_overlaps(combined, warnings=layout.warnings)

    # ⑤ 순서 배정: 모델 순서를 아는 영역은 그대로, 모르는 영역(고아)은
    #    기하 순서상 바로 앞 영역 뒤에 끼워 넣습니다.
    ordered_by_geometry = geometric_order(final_regions, page, warnings=layout.warnings)

    sort_keys: dict[int, tuple[float, int]] = {}
    last_known = -1.0
    tiebreak = 0
    for region in ordered_by_geometry:
        if region.paddle_order is not None:
            last_known = float(region.paddle_order)
            tiebreak = 0
            sort_keys[id(region)] = (last_known, 0)
        else:
            tiebreak += 1
            sort_keys[id(region)] = (last_known, tiebreak)

    layout.regions = sorted(ordered_by_geometry, key=lambda r: sort_keys[id(r)])

    # ⑥ 순서 정합성 검사: 기하 순서와 모델 순서가 크게 어긋나면 기록해 둡니다.
    known_orders = [
        r.paddle_order for r in ordered_by_geometry if r.paddle_order is not None
    ]
    if len(known_orders) > 2:
        inversions = _count_inversions(known_orders)
        pairs = len(known_orders) * (len(known_orders) - 1) / 2
        layout.order_conflicts = inversions
        if pairs and inversions / pairs > 0.25:
            layout.warnings.append(
                f"모델 순서와 기하 순서가 {inversions}쌍 어긋납니다. 다단 판단을 확인하세요."
            )

    return layout