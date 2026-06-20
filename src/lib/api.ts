// Client for the local FastAPI sidecar. Base URL is injected at build time
// (Vite env) so the same front works against a dev server or the bundled sidecar.
const BASE = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8008";

export interface HealthResponse {
  status: string;
  profile: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`Backend returned ${res.status}`);
  return res.json() as Promise<HealthResponse>;
}
