import { API_BASE_URL } from "../config/apiConfig";

export async function uploadDocument(file, { signal, groundTruthFile, force = false } = {}) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("force", String(force));

  if (groundTruthFile) {
    formData.append("ground_truth", groundTruthFile);
  }

  const response = await fetch(`${API_BASE_URL}/ai/document`, {
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

export async function fetchDocuments(query = "", offset = 0, signal) {
  const response = await fetch(`${API_BASE_URL}/documents?${new URLSearchParams({ q: query, offset })}`, { signal });
  if (!response.ok) throw new Error("저장된 문서를 불러오지 못했습니다.");
  return response.json();
}

export async function fetchDocument(id, signal) {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`, { signal });
  if (!response.ok) throw new Error("문서 이력을 불러오지 못했습니다.");
  return response.json();
}

export async function deleteDocument(documentId, summaryId = null) {
  const path = summaryId === null ? `/documents/${documentId}` : `/documents/${documentId}/summaries/${summaryId}`;
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "DELETE" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? "삭제하지 못했습니다. 다시 시도해 주세요.");
  }
}