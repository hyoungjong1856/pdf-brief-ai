"""PDF가 아닌 입력 파일을 기존 파이프라인이 이해하는 형태로 변환합니다.

지원 방식은 크게 세 갈래로 나뉩니다.

1. 일반 텍스트(.txt, .md) — 레이아웃·OCR이 필요 없으므로 바로 텍스트로 읽어
   요약 단계로 직행합니다. page_count 등 PDF 전용 진단 정보는 의미가 없어
   응답에서 고정값으로 채워집니다.
2. 오피스 문서(.docx, .doc, .pptx) — LibreOffice(soffice) 헤드리스 모드로
   PDF 변환한 뒤, 기존 PDF 파이프라인(레이아웃 판단 + 이미지 OCR)을 그대로
   재사용합니다. 표·이미지·레이아웃이 대부분 보존됩니다.
3. 이미지(.png, .jpg, .jpeg) — PDF로 감싸지 않고 RGB PNG로 정규화한 뒤
   바로 이미지 OCR 경로(hybrid_service.extract_image_document /
   ollama_service.analyze_image)로 보냅니다. 페이지·레이아웃 개념이 없는
   입력이므로 PDF 파이프라인을 거칠 이유가 없습니다.

.hwp/.hwpx(한글 문서)는 이 셋 중 어디에도 깔끔히 들어가지 않습니다. 자세한
설명은 hwp_to_pdf_bytes()의 docstring을 참고하세요 — 현재는 명시적으로
지원하지 않음(501)으로 처리합니다.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

PLAIN_TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
OFFICE_EXTENSIONS = {".docx", ".doc", ".pptx"}
HWP_EXTENSIONS = {".hwp", ".hwpx"}

SUPPORTED_EXTENSIONS = (
    {".pdf"} | PLAIN_TEXT_EXTENSIONS | IMAGE_EXTENSIONS | OFFICE_EXTENSIONS | HWP_EXTENSIONS
)

# LibreOffice 변환은 문서 크기·서버 부하에 따라 수 초~수십 초가 걸릴 수 있어
# 넉넉하게 잡습니다. 이미지/PDF 파이프라인의 다른 타임아웃과는 무관합니다.
OFFICE_CONVERT_TIMEOUT_SEC = 120


def extension_of(filename: str) -> str:
    """파일 이름에서 소문자 확장자를 뽑습니다. (예: "Report.PDF" -> ".pdf")"""

    return Path(filename or "").suffix.lower()


def read_plain_text(file_bytes: bytes) -> str:
    """.txt / .md 파일을 텍스트로 읽습니다.

    ground_truth(.txt) 업로드와 동일한 규칙(UTF-8 고정, BOM 허용)을 씁니다.
    """

    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="텍스트 파일은 UTF-8 인코딩이어야 합니다.",
        ) from error


def normalize_image_to_png_bytes(file_bytes: bytes) -> bytes:
    """업로드된 이미지를 OCR 파이프라인이 바로 받을 수 있는 PNG 바이트로 정규화합니다.

    예전에는 이미지를 1페이지짜리 PDF로 감싼 뒤 PDF 파이프라인(레이아웃 판단,
    페이지 렌더링 등)을 다시 태웠습니다. 이미지는 애초에 페이지 레이아웃이나
    텍스트 레이어 판단이 필요 없는 입력이라, 그 왕복은 pymupdf로 PDF를 만들고
    다시 여는 오버헤드만 더할 뿐 실제로 하는 일은 "RGB PNG로 바꾸기"뿐이었습니다.
    지금은 그 변환만 하고 곧바로 이미지 OCR 경로(hybrid_service.extract_image_document /
    ollama_service.analyze_image)로 넘깁니다.
    """

    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            image = image.convert("RGB")
            png_buffer = io.BytesIO()
            image.save(png_buffer, format="PNG")
            return png_buffer.getvalue()
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="이미지 파일을 읽을 수 없습니다.",
        ) from error


def office_to_pdf_bytes(filename: str, file_bytes: bytes) -> bytes:
    """.docx/.doc/.pptx를 LibreOffice(soffice) 헤드리스 모드로 PDF 변환합니다.

    동기(블로킹) 함수입니다 — 호출하는 쪽에서 asyncio.to_thread로 감싸야
    이벤트 루프가 subprocess 대기 동안 멈추지 않습니다.

    필수 조건: 서버에 LibreOffice(soffice 실행 파일)가 설치되어 있어야
    합니다. 이 프로젝트의 requirements.txt는 파이썬 패키지만 관리하므로,
    배포 환경(Dockerfile 등)에 `apt-get install libreoffice` 같은 설치
    단계를 별도로 추가해야 합니다.
    """

    suffix = extension_of(filename) or ".docx"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        src_path = tmp_path / f"input{suffix}"
        src_path.write_bytes(file_bytes)

        try:
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--norestore",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(tmp_path),
                    str(src_path),
                ],
                check=True,
                capture_output=True,
                timeout=OFFICE_CONVERT_TIMEOUT_SEC,
            )
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=500,
                detail="서버에 LibreOffice(soffice)가 설치되어 있지 않습니다.",
            ) from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors="ignore").strip() or str(error)
            raise HTTPException(
                status_code=400,
                detail=f"문서를 PDF로 변환하는 데 실패했습니다: {detail}",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise HTTPException(
                status_code=504,
                detail="문서를 PDF로 변환하는 데 시간이 너무 오래 걸립니다.",
            ) from error

        out_path = tmp_path / "input.pdf"
        if not out_path.exists():
            raise HTTPException(
                status_code=400,
                detail="문서를 PDF로 변환하지 못했습니다.",
            )
        return out_path.read_bytes()


def hwp_to_pdf_bytes(filename: str, file_bytes: bytes) -> bytes:  # noqa: ARG001
    """.hwp / .hwpx는 현재 지원하지 않습니다.

    다른 포맷과 달리 "PDF로 바꿔서 기존 파이프라인에 태운다"는 전략이
    그대로 통하지 않습니다.

    - .hwp(바이너리, ~2014 이전 규격)는 신뢰할 만한 오픈소스 변환기가
      사실상 없습니다. LibreOffice 기본 빌드는 HWP 임포트 필터를 포함하지
      않고, 안정적인 변환은 한글과컴퓨터 자체 도구(Windows 전용, 상용)나
      외부 변환 API 연동이 사실상 유일한 방법입니다.
    - .hwpx(2014+ zip+XML 규격)는 자체 파서를 작성할 수는 있지만, 텍스트만
      뽑을 수 있고 레이아웃·이미지 OCR은 사실상 불가능해 다른 포맷들과
      파이프라인 성격 자체가 달라집니다 (레이아웃 융합·이미지 OCR 진단
      필드들이 전부 의미를 잃습니다).

    따라서 별도 설계 논의 없이 기존 파이프라인에 끼워 넣지 않고, 명시적으로
    막아둡니다.
    """

    raise HTTPException(
        status_code=501,
        detail=(
            "HWP/HWPX 문서는 아직 지원하지 않습니다. "
            "외부 변환 도구(또는 API) 연동이 필요합니다 — 우선 PDF나 DOCX로 "
            "내보내서 업로드해 주세요."
        ),
    )