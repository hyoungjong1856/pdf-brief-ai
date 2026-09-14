import json

import httpx

from app.config import (
    MAX_DOCUMENT_CHARS,
    OCR_MODEL_NAME,
    OLLAMA_CHAT_URL,
    OLLAMA_GENERATE_URL,
    OLLAMA_TIMEOUT,
    SUMMARY_MODEL_NAME,
)
from app.schemas import PdfAnalysisContent

# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

# 텍스트 기반 / 이미지 기반 양쪽 모두에 적용되는 프롬프트입니다.
# 추출 경로가 달라도 최종 출력 형식은 동일하게 유지합니다.
ANALYSIS_SYSTEM_PROMPT = (
    "당신은 PDF 문서 어시스턴트입니다. 아래의 규칙을 반드시 지키세요.\n"
    "- 모든 답변은 한국어로 작성하세요.\n"
    "- 모든 답변은 JSON 형식으로 출력하세요.\n"
    "- 다른 설명이나 마크다운 코드블록 없이 순수 JSON만 반환하세요.\n"
    "- 답변은 총 3가지입니다: document, summary, keyword\n"
    "- document는 문서 본문을 마크다운 형식으로 정리한 내용입니다.\n"
    "- summary는 문서 전체를 요약한 내용입니다.\n"
    "- keyword는 핵심어를 쉼표로 구분한 목록입니다.\n"
    "- 반환 형식: "
    '{"document": "마크다운 본문", '
    '"summary": "요약", '
    '"keyword": "키워드1, 키워드2, 키워드3"}'
)

# 이미지 기반 PDF의 페이지 이미지를 읽을 때 사용하는 프롬프트입니다.
OCR_SYSTEM_PROMPT = (
    "당신은 이미지 속 내용을 있는 그대로 정확하게 옮겨 적는 어시스턴트입니다. "
    "요약하거나 해석하지 말고, 이미지에 보이는 텍스트와 표/차트/그림 등 시각 요소를 "
    "빠짐없이 최대한 그대로 서술하세요."
)

OCR_USER_PROMPT = "이 이미지의 내용을 그대로 옮겨 적으세요."


# ---------------------------------------------------------------------------
# OCR (이미지 기반 PDF)
# ---------------------------------------------------------------------------


def ocr_page_images(page_images: list[str]) -> str:
    """페이지 이미지(Base64 PNG) 목록을 OCR 모델에 순서대로 보내 텍스트로 만듭니다."""

    text_parts: list[str] = []

    for page_number, image_base64 in enumerate(page_images, start=1):
        payload = {
            "model": OCR_MODEL_NAME,
            "system": OCR_SYSTEM_PROMPT,
            "prompt": OCR_USER_PROMPT,
            # Ollama REST API의 images 필드는 Base64 이미지 문자열을 받습니다.
            "images": [image_base64],
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0,
                "num_ctx": 8192,
            },
        }

        response = httpx.post(
            OLLAMA_GENERATE_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )

        if response.is_error:
            print(f"OCR 모델 응답 오류 ({page_number}쪽):", response.status_code)
            print("응답 본문:", response.text)

        response.raise_for_status()

        page_text = response.json()["response"].strip()

        if page_text:
            text_parts.append(f"--- 페이지 {page_number} ---\n{page_text}")

    return "\n\n".join(text_parts)


# ---------------------------------------------------------------------------
# 본문 / 요약 / 키워드
# ---------------------------------------------------------------------------


def ask_summary_model(prompt: str) -> str:
    """요약 모델에 프롬프트를 보내고 원문 응답을 그대로 돌려받습니다."""

    payload = {
        "model": SUMMARY_MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": ANALYSIS_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "keep_alive": "10m",
        # 프롬프트로만 JSON을 요청하는 것보다 파싱 실패가 훨씬 줄어듭니다.
        "format": "json",
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }

    response = httpx.post(
        OLLAMA_CHAT_URL,
        json=payload,
        timeout=OLLAMA_TIMEOUT,
    )

    if response.is_error:
        print("요약 모델 응답 오류:", response.status_code)
        print("응답 본문:", response.text)

    response.raise_for_status()

    return response.json()["message"]["content"].strip()


def analyze_document(text: str) -> PdfAnalysisContent:
    """추출된 텍스트에서 본문(마크다운), 요약, 키워드를 생성합니다."""

    document = text[:MAX_DOCUMENT_CHARS]

    prompt = f"다음 PDF 문서를 분석해 주세요.\n\n문서 내용:\n{document}"

    raw = ask_summary_model(prompt)

    # format="json"을 써도 모델이 코드블록을 붙이는 경우가 있어 방어합니다.
    cleaned = raw.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```")
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 모델이 JSON 형식을 지키지 않아도 서비스가 중단되지 않게,
        # 받은 응답을 본문 자리에 그대로 담아 반환합니다.
        print("요약 모델 JSON 파싱 실패. 원문을 document에 담아 반환합니다.")
        return PdfAnalysisContent(document=raw)

    if not isinstance(data, dict):
        return PdfAnalysisContent(document=raw)

    return PdfAnalysisContent(
        document=str(data.get("document", "")),
        summary=str(data.get("summary", "")),
        keyword=str(data.get("keyword", "")),
    )