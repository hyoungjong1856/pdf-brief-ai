import httpx

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

OLLAMA_BASE_URL = "http://localhost:11434"

MODEL_NAME = "qwen2.5:7b"

def ask_ollama(message: str) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": (
                    "답변은 핵심만 간결하게 설명하세요."
                    "특별한 요청이 없다면 최대 5문장 이내로 답변하세요."
                    "불필요한 서론, 반복 설명, 이모티콘, 추가 질문은 하지 마세요."
                ),
            },
            {
                "role": "user",
                "content": message,
            },
        ],
        "stream": False,
        "keep_alive": "10m",
        "options": {
        "num_ctx": 4096,
        },
    }

    response = httpx.post(
        OLLAMA_CHAT_URL,
        json=payload,
        timeout=300.0,
    )

    response.raise_for_status()

    data = response.json()

    return data["message"]["content"]


def check_ollama_alive() -> bool:
    try:
        response = httpx.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=5.0,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def summarize_text(text: str) -> str:
    prompt = (
        "다음 문서를 3문장 이내로 요약해줘.\n\n"
        f"{text}"
    )
    return ask_ollama(prompt)


#############################
# PDF 작업을 위한 추가 사항
#############################

import json

def extract_keywords_and_summary(text: str) -> dict:
    prompt = (
        "다음 문서를 분석해서 아래 JSON 형식으로만 답변해줘. "
        "다른 설명이나 마크다운 코드블록 없이 순수 JSON만 출력해.\n\n"
        '{"keyword": "키워드1, 키워드2, 키워드3", "summary": "3문장 이내 요약"}\n\n'
        f"문서 내용:\n{text}"
    )
    raw = ask_ollama(prompt)

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 모델이 JSON 형식을 안 지켰을 때의 fallback
        return {"keyword": "", "summary": raw.strip()}

    return {
        "keyword": data.get("keyword", ""),
        "summary": data.get("summary", ""),
    }