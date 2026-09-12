import base64
import json
import os
from pathlib import Path

import fitz
import httpx
from dotenv import load_dotenv

# uvicorn을 어느 디렉터리에서 실행하더라도 backend/.env를 읽습니다.
# 이미 셸에서 설정한 환경 변수는 override=False로 유지합니다.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

OLLAMA_BASE_URL = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL") or f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_GENERATE_URL = (
    os.getenv("OLLAMA_GENERATE_URL") or f"{OLLAMA_BASE_URL}/api/generate"
)

OCR_MODEL_NAME = os.getenv("OLLAMA_OCR_MODEL")
SUMMARY_MODEL_NAME = os.getenv("OLLAMA_SUMMARY_MODEL")


# 요약 모델과 실제 통신
def ask_summary_model(prompt: str) -> str:
    payload = {
        "model": SUMMARY_MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": (
                    "당신은 PDF 문서 분석 도우미입니다. "
                    "반드시 요청한 JSON 형식만 반환하세요."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }

    response = httpx.post(
        OLLAMA_CHAT_URL,
        json=payload,
        timeout=300.0,
    )
    response.raise_for_status()

    return response.json()["message"]["content"].strip()


# 텍스트에서 키워드와 요약을 추출하는 함수
def extract_keywords_and_summary(text: str) -> dict[str, str]:
    """추출된 전체 텍스트에서 키워드와 요약을 생성합니다."""

    # 초기 버전의 컨텍스트 초과 방지용 제한입니다.
    # 긴 문서의 전체 요약은 이후 청크 요약 방식으로 개선할 수 있습니다.
    document = text[:24_000]

    prompt = (
        "다음 PDF 문서를 분석해줘.\n"
        "다른 설명이나 마크다운 코드블록 없이 순수 JSON만 반환해.\n\n"
        '반환 형식: {"keyword": "키워드1, 키워드2, 키워드3", '
        '"summary": "한국어 3문장 이내 요약"}\n\n'
        f"문서 내용:\n{document}"
    )

    raw = ask_summary_model(prompt)

    # 모델이 ```json 코드 블록을 붙여도 JSON만 남기도록 처리합니다.
    cleaned = raw.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```")
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 모델이 JSON 형식을 지키지 않아도 서비스가 중단되지 않게 처리합니다.
        return {
            "keyword": "",
            "summary": raw,
        }

    return {
        "keyword": str(data.get("keyword", "")),
        "summary": str(data.get("summary", "")),
    }


# 스캔 PDF를 이미지로 변환 -> OCR 모델로 텍스트를 추출하는 함수
def extract_text_with_ocr(file_bytes: bytes) -> str:
    """스캔 PDF를 페이지 이미지로 변환한 뒤 GLM-OCR로 텍스트를 읽습니다."""

    # PyMuPDF가 메모리의 PDF 바이트를 열고 페이지별 접근을 제공합니다.
    document = fitz.open(
        stream=file_bytes,
        filetype="pdf",
    )
    text_parts: list[str] = []

    try:
        for page_number, page in enumerate(document, start=1):
            # OCR 모델이 인식할 수 있도록 PDF 페이지를 PNG 이미지로 렌더링합니다.
            pixmap = page.get_pixmap(
                dpi=200,
                alpha=False,
            )

            # Ollama REST API의 images 필드는 Base64 이미지 문자열을 받습니다.
            image_base64 = base64.b64encode(
                pixmap.tobytes("png"),
            ).decode("utf-8")

            payload = {
                "model": OCR_MODEL_NAME,
                "prompt": (
                    "이 문서 페이지의 텍스트를 정확하게 추출해줘. "
                    "표는 가능한 행과 열 구조를 유지해. "
                    "설명 없이 추출 결과만 반환해."
                ),
                "images": [image_base64],
                "stream": False,
                "keep_alive": "10m",
                "options": {
                    "temperature": 0,
                    "num_ctx": 8192,
                },
            }

            # response = httpx.post(
            #     OLLAMA_GENERATE_URL,
            #     json=payload,
            #     timeout=300.0,
            # )
            response = httpx.post(
                OLLAMA_GENERATE_URL,
                json=payload,
                timeout=300.0,
            )

            if response.is_error:
                print("GLM-OCR 상태 코드:", response.status_code)
                print("GLM-OCR 오류 본문:", response.text)

            response.raise_for_status()

            page_text = response.json()["response"].strip()

            if page_text:
                text_parts.append(
                    f"--- 페이지 {page_number} ---\n{page_text}",
                )

    finally:
        document.close()

    return "\n\n".join(text_parts)
