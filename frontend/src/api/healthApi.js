import { API_BASE_URL } from "../config/apiConfig";

export async function getHealth(signal) {
  const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return response.json();
}
