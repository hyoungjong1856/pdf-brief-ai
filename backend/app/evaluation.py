"""OCR 추출 결과를 정답 텍스트와 비교하는 평가 로직입니다."""

import re


def normalize_for_cer(text: str) -> str:
    """CER 비교 전에 "내용"만 남기고 "서식" 차이를 지우는 전처리 작업입니다.

    제거 대상:
    - 기호: |, -, *, #
    - 공백: 스페이스, 탭, 줄바꿈 등
    """

    text = re.sub(r"[|*#-]", "", text)
    return re.sub(r"\s+", "", text)


def levenshtein_distance(reference: str, hypothesis: str) -> int:
    """두 문자열 간 편집 거리(삽입·삭제·치환 횟수)를 계산합니다."""

    previous_row = list(range(len(hypothesis) + 1))

    for reference_index, reference_character in enumerate(reference, start=1):
        current_row = [reference_index]

        for hypothesis_index, hypothesis_character in enumerate(hypothesis, start=1):
            substitution_cost = int(reference_character != hypothesis_character)
            current_row.append(
                min(
                    current_row[hypothesis_index - 1] + 1,
                    previous_row[hypothesis_index] + 1,
                    previous_row[hypothesis_index - 1] + substitution_cost,
                ),
            )

        previous_row = current_row

    return previous_row[-1]


def calculate_cer(reference_text: str, extracted_text: str) -> float | None:
    """양쪽 텍스트를 정규화한 CER을 반환합니다. 삽입이 많으면 1을 넘습니다."""

    reference = normalize_for_cer(reference_text)
    hypothesis = normalize_for_cer(extracted_text)

    if not reference:
        return None

    return levenshtein_distance(reference, hypothesis) / len(reference)


def get_text_length_metrics(
    extracted_text: str,
    reference_text: str | None = None,
) -> dict[str, int | None]:
    """CER 계산 전후의 문자 수를 반환합니다."""

    return {
        "extracted_text_length": len(extracted_text),
        "normalized_extracted_text_length": len(normalize_for_cer(extracted_text)),
        "normalized_ground_truth_text_length": (
            len(normalize_for_cer(reference_text))
            if reference_text is not None
            else None
        ),
    }
