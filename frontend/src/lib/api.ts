import type { RecognizeResponse, ScanLogItem, StatsResponse, VerifyRequest } from "./types";

const API_BASE = ""; // same-origin (nginx reverse proxy) | set to "http://localhost:8000" if needed

async function parseError(res: Response) {
  const text = await res.text();
  try {
    const j = JSON.parse(text);
    return j?.detail ?? text;
  } catch {
    return text || `HTTP ${res.status}`;
  }
}

export async function getStats(): Promise<StatsResponse> {
  const res = await fetch(`${API_BASE}/api/dashboard/stats`, { cache: "no-store" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

// Recommended backend endpoint (you should implement):
// GET /api/queue/pending?limit=50
export async function getPendingQueue(limit = 50): Promise<ScanLogItem[]> {
  const res = await fetch(`${API_BASE}/api/queue/pending?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function verifyLog(logId: number, payload: VerifyRequest): Promise<any> {
  const res = await fetch(`${API_BASE}/api/verify/${logId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function recognizeImage(file: File): Promise<RecognizeResponse> {
  const form = new FormData();
  form.append("image", file);

  const res = await fetch(`${API_BASE}/api/recognize`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
