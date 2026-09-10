const configuredUrl = import.meta.env.VITE_API_BASE_URL;

if (!configuredUrl) {
  console.warn(
    "VITE_API_BASE_URL이 설정되지 않아 기본 주소를 사용합니다.",
  );
}

export const API_BASE_URL =
  configuredUrl ?? "http://127.0.0.1:8000";
