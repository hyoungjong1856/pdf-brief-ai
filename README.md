# PDF Brief AI

PDF를 업로드하면 로컬 Ollama 모델이 텍스트를 추출하고 키워드와 한국어 요약을 생성합니다.
React 화면에서 분석 결과를 확인하고, SQLite 문서 보관함에서 저장된 요약을 검색·조회·삭제할 수 있습니다.

## 프로젝트 구조

```text
pdf-brief-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # PDF 분석 및 문서 보관함 API
│   │   ├── ollama_service.py    # Ollama 이미지 분석 요청
│   │   ├── evaluation.py        # 문자 오류율(CER) 및 텍스트 길이 계산
│   │   ├── database.py          # SQLite 문서·요약 이력 저장
│   │   └── schemas.py           # 응답 스키마
│   ├── tests/                  # DB 및 문서 API 테스트
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                # 백엔드 API 호출
│   │   ├── components/         # 공통 화면 구성 요소
│   │   ├── pages/              # 홈 및 개발자 평가 화면
│   │   ├── config/             # API 주소 설정
│   │   └── utils/              # 파일 검증 등
│   └── package.json
└── README.md
```

## 환경 설정

Python, Node.js/npm, Ollama가 필요합니다. 아래 명령은 저장소 루트에서 시작합니다.

### 백엔드

macOS/Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

이미 `backend/.env`가 있다면 복사하지 않고 기존 설정을 확인합니다.
기본 예시는 다음과 같습니다.

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_URL=http://127.0.0.1:11434/api/chat
OLLAMA_ANALYSIS_MODEL=qwen2.5vl:7b
```

`OLLAMA_ANALYSIS_MODEL`은 필수이며 이미지 입력을 지원하는 모델을 지정해야 합니다.

### 프런트엔드

별도 터미널에서 저장소 루트 기준으로 실행합니다.

```bash
cd frontend
npm ci
```

API 기본 주소는 `http://127.0.0.1:8000`입니다.
변경하려면 `frontend/.env`에 다음 값을 설정합니다.

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 실행 방법

### 1. Ollama

```bash
ollama serve
```

Ollama 앱이나 서비스가 이미 실행 중이라면 생략합니다.
최초 사용 시 별도 터미널에서 설정한 모델을 다운로드합니다.

```bash
ollama pull qwen2.5vl:7b
```

### 2. 백엔드

`backend` 폴더에서 가상환경을 활성화한 뒤 실행합니다.

```bash
python -m uvicorn app.main:app --reload
```

### 3. 프런트엔드

`frontend` 폴더에서 실행합니다.

```bash
npm run dev
```

- 홈: <http://localhost:5173/>
- 개발자 평가: <http://localhost:5173/developer>
- API 문서: <http://127.0.0.1:8000/docs>
- 백엔드 상태: <http://127.0.0.1:8000/health>

각 서버를 실행한 터미널에서 `Ctrl+C`로 종료합니다.

## PDF 분석 흐름

```text
React → FastAPI → PDF 페이지 이미지 변환 → Ollama → SQLite 저장 → 결과 표시
```

- `POST /ai/pdf`는 모든 PDF 페이지를 200 DPI 이미지로 변환하고, 한 번의 Ollama `/api/chat` 요청으로 `extracted_text`, `keyword`, `summary`를 받습니다.
- 페이지별 요청이나 별도 요약 요청은 보내지 않습니다.
- 현재 모델 요청은 `num_ctx: 8192`, `keep_alive: "10m"`, 타임아웃 300초로 설정되어 있습니다.
- 모든 페이지 이미지와 출력이 모델의 처리 범위에 들어가야 하므로 긴 문서는 메모리·문맥·출력 길이 제한에 영향을 받습니다.
- 형식이 잘못되거나 출력 제한으로 잘린 응답은 오류로 반환하며 추가 모델 요청은 하지 않습니다.
- 개발자 평가에서 UTF-8 `.txt` 정답 파일을 함께 업로드하면 모델이 추출한 텍스트의 문자 오류율(CER)을 계산합니다.
- `extraction_time_ms`는 PDF 진단과 모델의 추출·요약 처리를 포함한 시간입니다.

## SQLite 문서 보관함

분석 결과는 기본적으로 `backend/data/documents.db`에 저장됩니다.
별도 DB 설치는 필요하지 않으며 첫 DB 접근 시 파일과 테이블이 생성됩니다.
저장 위치는 `DOCUMENTS_DB_PATH` 환경변수로 변경할 수 있습니다.

- PDF 내용의 SHA-256 해시로 중복을 확인합니다. 파일명이 달라도 바이트가 같으면 기존 문서입니다.
- 같은 PDF를 다시 올리면 최근 저장된 결과를 반환합니다.
- 재분석 옵션을 선택하거나 API에 `force=true`를 보내면 같은 문서 아래 새 요약 이력을 추가합니다.
- 정답 텍스트를 함께 올리는 개발자 평가 요청도 다시 분석하여 새 이력을 저장합니다.
- 파일명, 키워드, 모든 요약 이력을 검색할 수 있습니다. 목록에는 최신 요약이 표시되며 상세 화면에서 이전 이력을 선택할 수 있습니다.
- ‘선택한 요약 삭제’는 해당 이력만, ‘문서 전체 삭제’는 문서와 모든 이력을 삭제합니다.
- 마지막 요약을 삭제해도 문서는 유지되며, 같은 PDF를 다시 올리면 새 요약을 저장합니다.
- PDF 원본은 보관하지 않습니다. 추출 텍스트와 진단 정보를 포함한 분석 응답은 DB에 저장됩니다.
- 사용자 구분 없는 로컬 공용 보관함이며 조회하려면 백엔드가 실행 중이어야 합니다.
- 기본 DB 폴더는 Git에서 제외됩니다. 백엔드를 종료한 상태에서 DB 파일을 복사해 백업할 수 있습니다.

## API

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/health` | 백엔드 프로세스 상태 확인 |
| POST | `/ai/pdf` | PDF 분석 또는 기존 결과 조회 |
| GET | `/documents` | 문서 검색 및 목록 조회 (`q`, `limit`, `offset`) |
| GET | `/documents/{document_id}` | 문서와 요약 이력 조회 |
| DELETE | `/documents/{document_id}` | 문서와 모든 요약 삭제 |
| DELETE | `/documents/{document_id}/summaries/{summary_id}` | 선택한 요약 삭제 |

`POST /ai/pdf`는 `multipart/form-data`로 필수 `file`(PDF), 선택 `ground_truth`(정답 TXT), 선택 `force`(기본값 `false`)를 받습니다.

## 검증

`backend` 폴더에서 가상환경을 활성화한 뒤 실행합니다.

```bash
python -m unittest discover -s tests -v
```

현재 백엔드 테스트는 임시 DB를 사용하여 중복 저장, 요약 이력, 검색, 삭제 및 API 동작을 검증합니다.
API 테스트의 분석 결과는 가짜 응답으로 대체하며 실제 Ollama를 호출하지 않습니다.

`frontend` 폴더에서 실행합니다.

```bash
node --test src/utils/validateFile.test.js
npm run lint
npm run build
```

## Ollama 상태 확인

```bash
ollama list                    # 설치된 모델 목록
ollama ps                      # 현재 메모리에 로드된 모델
ollama stop qwen2.5vl:7b        # 사용 후 모델을 메모리에서 해제
```
