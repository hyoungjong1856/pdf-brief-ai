export const MAX_FILE_SIZE = 5 * 1024 * 1024;

const ALLOWED_TYPES = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
]);

export function validateFile(file) {
  if (!file) {
    return "파일을 선택하세요.";
  }

  if (!ALLOWED_TYPES.has(file.type)) {
    return "PDF, PNG, JPG 파일만 사용할 수 있습니다.";
  }

  if (file.size > MAX_FILE_SIZE) {
    return "파일은 5MB 이하여야 합니다.";
  }

  return "";
}
