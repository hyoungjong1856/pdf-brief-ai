# Python + FastAPI + Ollama Local API 통합 실습

## 현재 PDF 분석 흐름

`POST /ai/pdf`는 모든 PDF 페이지를 이미지로 변환해 Ollama `/api/chat`에
한 번 요청하고, `extracted_text`, `keyword`, `summary`를 함께 받습니다.
페이지별 요청이나 별도 요약 요청은 보내지 않습니다.
CER은 응답의 추출문으로 계산합니다. 기존 `extraction_time_ms`는 이제 추출과 요약을 합친 처리 시간입니다.

`backend/.env`의 `OLLAMA_ANALYSIS_MODEL`에 이미지 입력을 지원하는 모델을 설정하세요.
미설정 시 기존 `OLLAMA_SUMMARY_MODEL`, `OLLAMA_OCR_MODEL` 순으로 사용합니다.
모든 페이지 이미지와 전체 추출문이 한 요청의 모델 용량 안에 들어가야 하므로,
긴 문서는 메모리·컨텍스트·출력 길이 제한에 영향을 받습니다.
형식이 잘못되거나 출력 제한으로 잘린 응답은 오류로 반환하며 추가 모델 요청은 하지 않습니다.

아래 내용은 초기 실습 예시입니다.

## 개요

Client → FastAPI → Ollama Local API → Local Model 구조를 직접 구현한
실습 프로젝트입니다.


```text
Client
↓
HTTP POST
↓
FastAPI
↓
AI Service (ollama_service.py)
↓
Ollama Local API (localhost:11434)
↓
Ollama Runtime
↓
Local Model
↓
Response
```

---

## 프로젝트 구조

```text
Python_FastAPI_Ollama_Local_API_Practice/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI Route
│   ├── schemas.py           # Request / Response Schema (Pydantic)
│   └── ollama_service.py    # Ollama 통신 로직
├── test_ollama_service.py   # Service 단독 테스트용 스크립트
├── requirements.txt
└── README.md
```

---

## 사용 모델

```text
llama3.1:8b   (약 5.1GB VRAM 사용, RTX 4060 8GB에서 GPU 가속 정상 동작 확인)
```



---

## 환경 설정

### 1. 가상환경 생성 및 활성화

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. 패키지 설치

```powershell
pip install fastapi uvicorn httpx
```

또는 requirements.txt로 한 번에:

```powershell
pip install -r requirements.txt
```

### 3. Ollama 사전 준비

```powershell
ollama ls              # 모델 목록 확인
ollama ps               # 현재 로드된 모델 확인
ollama run llama3.1:8b   # 모델 정상 동작 확인
```

---

## 실행 방법

두 개의 서버가 동시에 필요합니다. **터미널을 두 개 이상** 열어서 진행합니다.

### 터미널 1 — Ollama 서버

```powershell
ollama serve
```

(이미 트레이 아이콘으로 자동 실행 중이면 생략 가능. 포트: `11434`)

### 터미널 2 — FastAPI 서버

```powershell
uvicorn app.main:app --reload
```

(포트: `8000`)

### 터미널 3 — 테스트용

```powershell
curl http://127.0.0.1:8000/health
```

---

## 제공 엔드포인트

| Method | Endpoint       | 설명                              |
|--------|----------------|-----------------------------------|
| GET    | `/health`      | FastAPI 프로세스 자체 생존 확인      |
| GET    | `/health/ai`   | FastAPI → Ollama 연결 상태까지 확인 |
| POST   | `/ai/chat`     | 일반 채팅 (system message 포함)     |
| POST   | `/ai/summary`  | 문서 요약                          |

Swagger UI로 직접 테스트 가능:

```text
http://127.0.0.1:8000/docs
```

### `/ai/chat` 요청 예시

```json
{
  "message": "AI Model이 무엇인지 설명해줘."
}
```

응답 예시 (model 필드 포함, 응용 과제 반영):

```json
{
  "model": "llama3.1:8b",
  "answer": "..."
}
```

### `/ai/summary` 요청 예시

```json
{
  "text": "요약하고 싶은 긴 문단..."
}
```

응답 예시:

```json
{
  "summary": "..."
}
```

---

## 종료 방법

### 정상 종료 (권장)

각 서버를 실행한 터미널 창에서 **Ctrl+C**

```text
터미널 1 (ollama serve)  → Ctrl+C
터미널 2 (uvicorn)        → Ctrl+C
```

Ctrl+C가 한 번에 안 먹으면 2~3번 눌러보거나, 터미널 창을 클릭해
포커스를 준 뒤 다시 시도.

### 강제 종료 (Ctrl+C가 안 먹을 때)

```powershell
# 1. 포트 점유 프로세스 확인
netstat -ano | findstr :11434    # Ollama
netstat -ano | findstr :8000     # FastAPI

# 2. 해당 PID 강제 종료
taskkill /PID <PID> /F
```

### 전체 종료 확인

```powershell
netstat -ano | findstr :11434
netstat -ano | findstr :8000
```

두 명령 모두 아무것도 안 뜨면 완전히 종료된 상태.

---

## 핵심 코드 요약

### `app/schemas.py`

```python
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=2000,
    )


class ChatResponse(BaseModel):
    model: str
    answer: str


class SummaryRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=5000,
    )


class SummaryResponse(BaseModel):
    summary: str
```

### `app/ollama_service.py`

```python
import httpx

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

OLLAMA_BASE_URL = "http://localhost:11434"

MODEL_NAME = "llama3.1:8b"

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
```

### `app/main.py`

```python
import httpx

from fastapi import FastAPI, HTTPException

from app.ollama_service import ask_ollama, MODEL_NAME, check_ollama_alive
from app.schemas import ChatRequest, ChatResponse

from app.schemas import (
    ChatRequest,
    ChatResponse,
    SummaryRequest,
    SummaryResponse,
)
from app.ollama_service import (
    ask_ollama,
    MODEL_NAME,
    check_ollama_alive,
    summarize_text,
)


app = FastAPI(
    title="AIKOS Local AI API",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
    }


@app.get("/health/ai")
def health_ai() -> dict[str, str]:
    if check_ollama_alive():
        return {"status": "ok"}
    return {"status": "unavailable"}


@app.post(
    "/ai/chat",
    response_model=ChatResponse,
)
def chat(
    request: ChatRequest,
) -> ChatResponse:
    try:
        answer = ask_ollama(
            request.message
        )

    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Local AI provider request failed.",
        ) from error

    return ChatResponse(
        model=MODEL_NAME,
        answer=answer
    )


@app.post(
    "/ai/summary",
    response_model=SummaryResponse,
)
def summary(
    request: SummaryRequest,
) -> SummaryResponse:
    result = summarize_text(request.text)

    return SummaryResponse(
        summary=result
    )
```

---

## 트러블슈팅 메모

### 포트 중복 에러 (`Only one usage of each socket address`)

Ollama가 이미 백그라운드(트레이 앱)로 떠 있는 상태에서 `ollama serve`를
중복 실행하면 발생. 기존 프로세스를 먼저 종료해야 함.

```powershell
netstat -ano | findstr :11434
taskkill /PID <PID> /F
```

### GPU / CPU 강제 전환 (테스트용)

```powershell
# CMD 기준
set CUDA_VISIBLE_DEVICES=-1     # GPU 비활성화 (CPU 전용)
set CUDA_VISIBLE_DEVICES=0      # 원상복구 (GPU 사용)

ollama serve
```

PowerShell에서는 `$env:CUDA_VISIBLE_DEVICES = "-1"` 문법 사용.

GPU 정상 사용 여부는 `nvidia-smi`의 **GPU-Util(%) / Memory-Usage**
변화로 판단. Processes 목록에 `llama-server.exe`가 떠 있는 것만으로는
GPU 연산 여부를 확정할 수 없음 (WDDM 창 렌더링 때문에 `C+G` 타입으로
잔상처럼 표시될 수 있음).

### Pylance `reportMissingImports: pydantic`

VS Code가 가상환경(.venv) 인터프리터를 잡지 못했을 때 발생.

```text
Ctrl+Shift+P → Python: Select Interpreter → .venv 선택
```

---

## Ollama 명령어 모음

```powershell
ollama serve                    # 서버 수동 실행
ollama run <모델명>              # 모델 실행 (서버 없으면 자동 실행)
ollama pull <모델명>             # 모델 다운로드만
ollama ls                       # 다운받은 모델 목록
ollama ps                       # 현재 메모리에 로드된 모델 확인
ollama stop <모델명>             # 특정 모델 메모리에서 내리기
ollama rm <모델명>               # 모델 삭제
```

---

## Windows 프로세스 / GPU 관리 명령어

### GPU 활성화/비활성화 (환경변수)

```powershell
set CUDA_VISIBLE_DEVICES=-1              # CMD: GPU 비활성화 (CPU만 사용)
set CUDA_VISIBLE_DEVICES=0               # 0번 GPU만 사용 (원상복구)

$env:CUDA_VISIBLE_DEVICES = "-1"         # PowerShell: 위와 동일
$env:CUDA_VISIBLE_DEVICES = "0"
```

> 서버(`ollama serve`)를 실행하는 세션에 환경변수를 설정해야 적용됨.
> `ollama run`만으로는 서버가 이미 떠 있는 상태면 적용 안 됨.

### 포트 점유 프로세스 확인

```powershell
netstat -ano | findstr :11434            # 11434 포트 점유 프로세스(PID) 확인
```

### 프로세스 정보 확인

```powershell
tasklist /FI "PID eq <PID>"              # 특정 PID 프로세스 정보 확인
tasklist | findstr /i ollama             # ollama 관련 프로세스만 필터링
where python                             # 현재 PATH상 python 실행 경로 확인
```

### 프로세스 강제 종료

```powershell
taskkill /PID <PID> /F                   # PID로 강제 종료
taskkill /IM ollama.exe /F               # 프로세스 이름으로 강제 종료
```

### 서비스 등록 여부 확인

```powershell
sc query | findstr /i ollama             # ollama가 Windows 서비스로 등록되어 있는지 확인
```

### GPU 상태 확인

```powershell
nvidia-smi                               # GPU 사용량 / 로드된 프로세스 확인
```

> `Processes` 목록에 `llama-server.exe`가 보여도 실제 GPU 연산 여부는
> **GPU-Util(%)** 와 **Memory-Usage** 변화로 판단해야 함
> (WDDM 환경에서는 창 렌더링만으로도 `C+G` 타입으로 잔상처럼 표시될 수 있음).

---



