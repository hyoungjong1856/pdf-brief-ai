export const MAX_FILE_SIZE = 5 * 1024 * 1024;

// 백엔드(app/file_ingest.py)의 SUPPORTED_EXTENSIONS와 동일하게 맞춥니다.
// file.type(MIME)은 .md, .hwp/.hwpx, 일부 오피스 문서에서 브라우저·OS마다
// 비어 있거나 제각각이라 신뢰할 수 없어, 파일 확장자로 검사합니다.
export const ALLOWED_EXTENSIONS = [
  ".pdf",
  ".txt",
  ".md",
  ".png",
  ".jpg",
  ".jpeg",
  ".docx",
  ".doc",
  ".pptx",
  ".hwp",
  ".hwpx",
];

const ALLOWED_EXTENSION_SET = new Set(ALLOWED_EXTENSIONS);

export function extensionOf(filename) {
  const match = /\.[^./\\]+$/.exec(filename || "");
  return match ? match[0].toLowerCase() : "";
}

export function validateFile(file) {
  if (!file) {
    return "파일을 선택하세요.";
  }

  if (!ALLOWED_EXTENSION_SET.has(extensionOf(file.name))) {
    return "지원하지 않는 파일 형식입니다. PDF, 이미지(PNG/JPG), 오피스 문서(DOCX/DOC/PPTX), 텍스트(TXT/MD), 한글(HWP/HWPX) 파일만 사용할 수 있습니다.";
  }

  if (file.size > MAX_FILE_SIZE) {
    return "파일은 5MB 이하여야 합니다.";
  }

  return "";
}