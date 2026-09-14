import os
from pathlib import Path

from dotenv import load_dotenv

# uvicorn을 어느 디렉터리에서 실행하더라도 backend/.env를 읽습니다.
# 이미 셸에서 설정한 환경 변수는 override=False로 유지합니다.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)


# ---------------------------------------------------------------------------
# Ollama 접속 정보
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL") or f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_GENERATE_URL = (
    os.getenv("OLLAMA_GENERATE_URL") or f"{OLLAMA_BASE_URL}/api/generate"
)

OCR_MODEL_NAME = (os.getenv("OLLAMA_OCR_MODEL") or "").strip()
SUMMARY_MODEL_NAME = (os.getenv("OLLAMA_SUMMARY_MODEL") or "").strip()

# 모델명이 비어 있으면 payload의 "model"이 빈 값으로 나가 런타임에야 502가 납니다.
# 서버가 뜨는 시점에 바로 실패시켜 원인을 명확히 합니다.
_missing = [
    name
    for name, value in (
        ("OLLAMA_OCR_MODEL", OCR_MODEL_NAME),
        ("OLLAMA_SUMMARY_MODEL", SUMMARY_MODEL_NAME),
    )
    if not value
]

if _missing:
    raise RuntimeError(
        f"환경 변수가 설정되지 않았습니다: {', '.join(_missing)}. "
        f"backend/.env 파일을 확인하세요. (참고: {ENV_FILE})"
    )


# ---------------------------------------------------------------------------
# 업로드 제한
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "5")) * 1024 * 1024

# OCR 경로에서는 페이지 수가 곧 처리 시간입니다. 상한을 두지 않으면
# 100페이지 스캔본 하나로 서버가 수십 분 동안 묶입니다.
MAX_PAGE_COUNT = int(os.getenv("MAX_PAGE_COUNT", "30"))


# ---------------------------------------------------------------------------
# 이미지 기반 PDF 판정 기준
# ---------------------------------------------------------------------------

# 내장 이미지가 이 개수 이상이면 이미지 기반으로 봅니다.
MIN_IMAGE_COUNT = int(os.getenv("MIN_IMAGE_COUNT", "1"))

# 이미지가 없어도 벡터 드로잉이 이 개수 이상이면 이미지 기반으로 봅니다.
# (도면, 벡터로 출력된 표/차트가 여기에 해당합니다.)
MIN_DRAWING_COUNT = int(os.getenv("MIN_DRAWING_COUNT", "50"))


# ---------------------------------------------------------------------------
# 모델 호출 옵션
# ---------------------------------------------------------------------------

OCR_DPI = int(os.getenv("OCR_DPI", "200"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))

# 컨텍스트 초과 방지용 제한입니다.
# 긴 문서 전체 처리는 이후 청크 분할 방식으로 개선할 수 있습니다.
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "24000"))