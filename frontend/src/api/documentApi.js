import { API_BASE_URL } from "../config/apiConfig";

export async function uploadDocument(file, { signal, groundTruthFile } = {}) {
  const formData = new FormData();
  formData.append("file", file);

  if (groundTruthFile) {
    formData.append("ground_truth", groundTruthFile);
  }

  const response = await fetch(`${API_BASE_URL}/ai/pdf`, {
    method: "POST",
    body: formData,
    signal,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${response.status}`);
  }

  return response.json();
}
