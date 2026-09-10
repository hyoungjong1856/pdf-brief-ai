import { httpClient } from "./httpClient";

export async function getHealthWithAxios(signal) {
  const response = await httpClient.get("/api/v1/health", {
    signal,
  });

  return response.data;
}
