const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export async function getKPI() {
  const res = await fetch(`${API_BASE}/api/dashboard/kpi`);
  if (!res.ok) throw new Error("failed to load KPI");
  return res.json();
}

export async function uploadSingle(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new Error("upload failed");
  return res.json();
}

export async function uploadBatch(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const res = await fetch(`${API_BASE}/api/upload/batch`, { method: "POST", body: fd });
  if (!res.ok) throw new Error("batch upload failed");
  return res.json();
}

export async function listPending(limit=100) {
  const res = await fetch(`${API_BASE}/api/reads/pending?limit=${limit}`);
  if (!res.ok) throw new Error("failed to load queue");
  return res.json();
}

export async function verifyRead(readId, payload) {
  const res = await fetch(`${API_BASE}/api/reads/${readId}/verify`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("verify failed");
  return res.json();
}

export async function deleteRead(readId) {
  const res = await fetch(`${API_BASE}/api/reads/${readId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("delete read failed");
  return res.json();
}

export async function searchMaster(q="") {
  const res = await fetch(`${API_BASE}/api/master?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error("failed to load master");
  return res.json();
}

export async function deleteMaster(masterId) {
  const res = await fetch(`${API_BASE}/api/master/${masterId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("delete master failed");
  return res.json();
}

export async function upsertMaster(payload) {
  const res = await fetch(`${API_BASE}/api/master`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("save master failed");
  return res.json();
}

export async function listCameras() {
  const res = await fetch(`${API_BASE}/api/cameras`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    console.error("listCameras failed", { status: res.status, text });
    const baseMessage = res.status === 404
      ? "/api/cameras not found or backend not running"
      : `Failed to load cameras (status ${res.status})`;
    const detail = text ? `: ${text}` : "";
    throw new Error(`${baseMessage}${detail}`);
  }
  return res.json();
}

export async function upsertCamera(payload) {
  const res = await fetch(`${API_BASE}/api/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("save camera failed");
  return res.json();
}

export async function rtspStart(payload) {
  const res = await fetch(`${API_BASE}/api/rtsp/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("rtsp start failed");
  return res.json();
}

export async function rtspStop(cameraId) {
  const res = await fetch(`${API_BASE}/api/rtsp/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ camera_id: cameraId })
  });
  if (!res.ok) throw new Error("rtsp stop failed");
  return res.json();
}

// image url already includes /api/images?path=...
export function absImageUrl(pathOrUrl) {
  if (!pathOrUrl) return "";
  if (pathOrUrl.startsWith("http")) return pathOrUrl;
  return `${API_BASE}${pathOrUrl}`;
}
