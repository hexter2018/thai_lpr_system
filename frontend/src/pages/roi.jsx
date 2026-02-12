import { useState, useEffect, useCallback, useRef } from "react";

// ─── CONFIG ──────────────────────────────────────────────────
const API_BASE = (() => {
  const configured = (import.meta.env.VITE_API_BASE || "").trim();
  if (configured) return configured.replace(/\/$/, "");
  return window.location.origin.replace(/\/$/, "");
})();

const WS_BASE = ((import.meta.env.VITE_WS_BASE || "").trim() || window.location.origin.replace(/^http/, "ws")).replace(/\/$/, "");

const ENABLE_MJPEG_STREAM =
  String(import.meta.env.VITE_ENABLE_MJPEG_STREAM || "true").toLowerCase() === "true";

const MAX_CAPTURED_TRACKS = 30;

// ─── CLIENT-SIDE MOTION TRACKER ──────────────────────────────
// ทำ frame differencing บน canvas เพื่อสร้าง pseudo track_id
// ไม่ต้อง WebSocket — ทำงานได้ทันทีกับ MJPEG stream
class ClientMotionTracker {
  constructor() {
    this.prevGray = null;
    this.tracks = new Map(); // id → {cx, cy, lastSeen, age}
    this.nextId = 1;
    this.offscreen = document.createElement("canvas");
    this.offCtx = this.offscreen.getContext("2d", { willReadFrequently: true });
  }

  // แปลงเป็น grayscale 1-channel array
  _toGray(data, w, h) {
    const gray = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) {
      const o = i * 4;
      gray[i] = (data[o] * 77 + data[o + 1] * 150 + data[o + 2] * 29) >> 8;
    }
    return gray;
  }

  // erode เล็กน้อยเพื่อลด noise
  _morphOpen(bin, w, h) {
    const out = new Uint8Array(w * h);
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = y * w + x;
        if (
          bin[i] &&
          bin[i - 1] && bin[i + 1] &&
          bin[i - w] && bin[i + w]
        ) out[i] = 1;
      }
    }
    return out;
  }

  // Connected components แบบ simple flood fill → รายการ blob
  _findBlobs(bin, w, h, minArea = 200) {
    const visited = new Uint8Array(w * h);
    const blobs = [];
    const stack = [];

    for (let start = 0; start < w * h; start++) {
      if (!bin[start] || visited[start]) continue;
      stack.length = 0;
      stack.push(start);
      let minX = w, maxX = 0, minY = h, maxY = 0, count = 0, sumX = 0, sumY = 0;

      while (stack.length) {
        const idx = stack.pop();
        if (visited[idx]) continue;
        visited[idx] = 1;
        const px = idx % w, py = (idx / w) | 0;
        if (px < minX) minX = px; if (px > maxX) maxX = px;
        if (py < minY) minY = py; if (py > maxY) maxY = py;
        sumX += px; sumY += py; count++;

        if (px > 0 && bin[idx - 1] && !visited[idx - 1]) stack.push(idx - 1);
        if (px < w - 1 && bin[idx + 1] && !visited[idx + 1]) stack.push(idx + 1);
        if (py > 0 && bin[idx - w] && !visited[idx - w]) stack.push(idx - w);
        if (py < h - 1 && bin[idx + w] && !visited[idx + w]) stack.push(idx + w);
      }

      if (count >= minArea) {
        blobs.push({
          cx: sumX / count / w,    // normalized 0-1
          cy: sumY / count / h,
          x1: minX / w, y1: minY / h,
          x2: maxX / w, y2: maxY / h,
          area: count,
        });
      }
    }
    return blobs;
  }

  // จับคู่ blob กับ track ที่มีอยู่ (nearest centroid)
  _matchBlobs(blobs) {
    const matched = new Set();
    const result = [];
    const MAX_DIST = 0.15; // max normalized distance to match
    const now = performance.now();

    // ลบ track เก่า (ไม่เห็นนาน > 2s)
    for (const [id, t] of this.tracks) {
      if (now - t.lastSeen > 2000) this.tracks.delete(id);
    }

    for (const blob of blobs) {
      let bestId = null, bestDist = MAX_DIST;

      for (const [id, t] of this.tracks) {
        if (matched.has(id)) continue;
        const d = Math.hypot(blob.cx - t.cx, blob.cy - t.cy);
        if (d < bestDist) { bestDist = d; bestId = id; }
      }

      if (bestId !== null) {
        // อัพเดท track ที่มีอยู่
        const t = this.tracks.get(bestId);
        t.cx = blob.cx; t.cy = blob.cy; t.lastSeen = now; t.age++;
        matched.add(bestId);
        result.push({ track_id: String(bestId), bbox: [blob.x1, blob.y1, blob.x2, blob.y2], ...blob });
      } else {
        // สร้าง track ใหม่
        const id = this.nextId++;
        this.tracks.set(id, { cx: blob.cx, cy: blob.cy, lastSeen: now, age: 0 });
        result.push({ track_id: String(id), bbox: [blob.x1, blob.y1, blob.x2, blob.y2], ...blob });
      }
    }

    return result;
  }

  // วิเคราะห์ frame จาก source (img/canvas) — คืน tracked objects
  detect(source, canvasW, canvasH) {
    const SW = 80, SH = 45; // downsample size เพื่อประหยัด CPU
    this.offscreen.width = SW;
    this.offscreen.height = SH;
    this.offCtx.drawImage(source, 0, 0, SW, SH);
    const imgData = this.offCtx.getImageData(0, 0, SW, SH);
    const gray = this._toGray(imgData.data, SW, SH);

    if (!this.prevGray) {
      this.prevGray = gray;
      return [];
    }

    // Frame difference + threshold
    const THRESH = 20;
    const diff = new Uint8Array(SW * SH);
    for (let i = 0; i < SW * SH; i++) {
      diff[i] = Math.abs(gray[i] - this.prevGray[i]) > THRESH ? 1 : 0;
    }
    this.prevGray = gray;

    const opened = this._morphOpen(diff, SW, SH);
    const blobs = this._findBlobs(opened, SW, SH, 150);
    return this._matchBlobs(blobs);
  }

  reset() {
    this.prevGray = null;
    this.tracks.clear();
  }
}

// ─── NORMALIZE HELPERS ───────────────────────────────────────
function normalizeTrackedObject(raw) {
  if (!raw || typeof raw !== "object") return null;
  const trackId = raw.track_id ?? raw.trackId ?? raw.id;
  if (typeof trackId === "undefined" || trackId === null) return null;
  const sourceBbox = raw.bbox ?? raw.box ?? raw.rect;
  let bbox = null;
  if (Array.isArray(sourceBbox) && sourceBbox.length >= 4) {
    bbox = sourceBbox.slice(0, 4).map((v) => Number(v));
  }
  if (!bbox || bbox.some((v) => Number.isNaN(v))) return null;
  return { ...raw, track_id: String(trackId), bbox };
}

function extractTrackedObjects(msg, selectedCam) {
  if (!msg || typeof msg !== "object") return [];
  const incomingCameraId = msg.camera_id ?? msg.cameraId ?? msg.cam_id;
  if (incomingCameraId && String(incomingCameraId) !== String(selectedCam)) return [];
  const candidates = [msg.objects, msg.tracks, msg.data?.objects, msg.data?.tracks];
  const list = candidates.find((arr) => Array.isArray(arr));
  if (!Array.isArray(list)) return [];
  return list.map(normalizeTrackedObject).filter(Boolean);
}

// ─── API FUNCTIONS ───────────────────────────────────────────
const API = {
  async cameras() {
    try {
      const res = await fetch(`${API_BASE}/api/roi-agent/cameras`);
      if (!res.ok) throw new Error(`${res.status}`);
      const raw = await res.json();
      return Array.isArray(raw) ? raw.map(c => c && (c.id || c.camera_id) ? { ...c, id: c.id || c.camera_id, name: c.name || c.id, status: c.status || "unknown" } : null).filter(Boolean) : null;
    } catch { return null; }
  },
  async snapshot(cameraId) {
    const res = await fetch(`${API_BASE}/api/roi-agent/snapshot/${cameraId}?width=1280&t=${Date.now()}`);
    if (!res.ok) { let d = `HTTP ${res.status}`; try { d = (await res.json()).detail || d; } catch (_) {} throw new Error(d); }
    return URL.createObjectURL(await res.blob());
  },
  async getRoi(cameraId) {
    try {
      const res = await fetch(`${API_BASE}/api/roi-agent/config/${cameraId}`);
      if (!res.ok) throw new Error(`${res.status}`);
      return await res.json();
    } catch { return null; }
  },
  async saveRoi(cameraId, roi) {
    try {
      const res = await fetch(`${API_BASE}/api/roi-agent/config/${cameraId}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(roi),
      });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `${res.status}`); }
      return await res.json();
    } catch (e) { return { ok: false, message: e.message }; }
  },
};

// ─── DESIGN TOKENS ───────────────────────────────────────────
const C = {
  bg: "#050810", card: "#0a1020", cardBorder: "#141f38", cardBorderActive: "#1e3a6e",
  text: "#a8bdd4", dim: "#3d5070", bright: "#e8f0f8",
  blue: "#2563eb", blueBright: "#3b82f6", blueGlow: "rgba(37,99,235,0.10)",
  green: "#10b981", greenDim: "rgba(16,185,129,0.08)",
  red: "#ef4444", redDim: "rgba(239,68,68,0.08)",
  amber: "#f59e0b", amberDim: "rgba(245,158,11,0.08)",
  purple: "#7c3aed", cyan: "#22d3ee",
};

const MOCK_CAMERAS = [
  { id: "PCN_Lane4", name: "PCN-MM04 Lane 4", status: "no_heartbeat", roi: { x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 } },
  { id: "PCN_Lane5", name: "PCN-MM04 Lane 5", status: "no_heartbeat", roi: null },
  { id: "PCN_Lane6", name: "PCN-MM04 Lane 6", status: "no_heartbeat", roi: null },
];

function StatusDot({ status }) {
  const color = status === "online" ? C.green : status === "stale" ? C.amber : status === "offline" ? C.red : C.dim;
  return <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: color, boxShadow: status === "online" ? `0 0 6px ${C.green}` : "none", flexShrink: 0 }} />;
}

// ─── MAIN COMPONENT ──────────────────────────────────────────
export default function ROIDashboard() {
  const [cameras, setCameras] = useState(null);
  const [selectedCam, setSelectedCam] = useState(null);
  const [streamMode, setStreamMode] = useState("live");
  const [snapshotUrl, setSnapshotUrl] = useState(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState(null);
  const [streamError, setStreamError] = useState(null);
  const [roi, setRoi] = useState({ x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 });
  const [savedRoi, setSavedRoi] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [useMock, setUseMock] = useState(false);
  const [connected, setConnected] = useState(false);
  const [trackedObjects, setTrackedObjects] = useState([]);
  const [triggerLine, setTriggerLine] = useState({ p1: { x: 0.20, y: 0.76 }, p2: { x: 0.88, y: 0.76 } });
  const [editMode, setEditMode] = useState("roi");
  const [capturedTracks, setCapturedTracks] = useState({});
  const [wsConnected, setWsConnected] = useState(false);
  // Client-side tracking mode flag
  const [clientTrackingActive, setClientTrackingActive] = useState(false);
  const [trackingSource, setTrackingSource] = useState("none"); // "websocket" | "client" | "none"

  const canvasRef = useRef(null);
  const imgRef = useRef(null);          // MJPEG <img> element
  const snapshotImgRef = useRef(null);  // snapshot image object
  const [dragging, setDragging] = useState(null);
  const trackStateRef = useRef({});
  const motionTrackerRef = useRef(null);
  const animFrameRef = useRef(null);
  const wsRef = useRef(null);

  const CANVAS_W = 960, CANVAS_H = 540;

  // ── Initialize motion tracker ──
  useEffect(() => {
    motionTrackerRef.current = new ClientMotionTracker();
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, []);

  // ── Stream URL (MJPEG) ──
  const streamUrl = selectedCam && ENABLE_MJPEG_STREAM
    ? `${API_BASE}/api/roi-agent/live/${encodeURIComponent(selectedCam)}/mjpeg`
    : null;

  // ── Load cameras ──
  useEffect(() => {
    (async () => {
      const data = await API.cameras();
      if (data && data.length > 0) {
        setCameras(data); setSelectedCam(data[0].id);
        if (data[0].roi) setRoi(data[0].roi);
        setConnected(true);
      } else {
        setUseMock(true); setConnected(false);
        setCameras(MOCK_CAMERAS); setSelectedCam(MOCK_CAMERAS[0].id);
        if (MOCK_CAMERAS[0].roi) setRoi(MOCK_CAMERAS[0].roi);
      }
    })();
  }, []);

  // ── Load ROI when camera changes ──
  useEffect(() => {
    if (!selectedCam) return;
    imgRef.current = null;
    setSnapshotUrl(prev => { if (prev) URL.revokeObjectURL(prev); return null; });
    setSnapshotError(null); setStreamError(null); setSaveResult(null);
    setTrackedObjects([]); setCapturedTracks({}); setWsConnected(false);
    trackStateRef.current = {};
    if (motionTrackerRef.current) motionTrackerRef.current.reset();
    setClientTrackingActive(false); setTrackingSource("none");
    (async () => {
      const data = await API.getRoi(selectedCam);
      if (data) { setRoi(data); setSavedRoi(data); }
    })();
  }, [selectedCam]);

  // ── WebSocket (primary tracking source) ──
  useEffect(() => {
    if (!selectedCam) return;
    let active = true, ws = null, reconnectTimer = null;

    const connect = () => {
      if (!active) return;
      try { ws = new WebSocket(`${WS_BASE}/ws/cameras/${encodeURIComponent(selectedCam)}`); }
      catch (_) { reconnectTimer = setTimeout(connect, 3000); return; }

      ws.onopen = () => { setWsConnected(true); setTrackingSource("websocket"); };
      ws.onclose = () => {
        setWsConnected(false);
        // ถ้า WebSocket ตาย → fallback client-side tracking
        if (active && streamMode === "live") setTrackingSource("client");
        if (active) reconnectTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => setWsConnected(false);
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          const objs = extractTrackedObjects(msg, selectedCam);
          if (objs.length > 0) {
            setTrackedObjects(objs);
            setTrackingSource("websocket");
          }
        } catch (_) {}
      };
    };

    const t = setTimeout(connect, 200);
    return () => {
      active = false; clearTimeout(t);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [selectedCam, streamMode]);

  // ── Client-side motion tracking loop (fallback) ──
  useEffect(() => {
    if (streamMode !== "live" || trackingSource === "websocket") return;
    setClientTrackingActive(true);
    let rafId = null;

    const tick = () => {
      const source = imgRef.current;
      if (source && source.naturalWidth > 0) {
        try {
          const objs = motionTrackerRef.current.detect(source, CANVAS_W, CANVAS_H);
          // กรองเฉพาะ track ที่ age > 1 (เพื่อลด noise)
          const stable = objs.filter(o => {
            const t = motionTrackerRef.current.tracks.get(Number(o.track_id));
            return t && t.age >= 1;
          });
          setTrackedObjects(stable);
          if (stable.length > 0) setTrackingSource("client");
        } catch (_) {}
      }
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    animFrameRef.current = rafId;
    return () => { cancelAnimationFrame(rafId); setClientTrackingActive(false); };
  }, [streamMode, trackingSource, selectedCam]);

  // ── Capture snapshot ──
  const captureSnapshot = useCallback(async () => {
    if (!selectedCam) return;
    setSnapshotLoading(true); setSnapshotError(null);
    try {
      const url = await API.snapshot(selectedCam);
      if (snapshotUrl) URL.revokeObjectURL(snapshotUrl);
      setSnapshotUrl(url);
    } catch (e) { setSnapshotError(e.message); }
    finally { setSnapshotLoading(false); }
  }, [selectedCam, snapshotUrl]);

  useEffect(() => {
    if (!snapshotUrl || streamMode !== "snapshot") return;
    const img = new Image();
    img.onload = () => { snapshotImgRef.current = img; };
    img.src = snapshotUrl;
  }, [snapshotUrl, streamMode]);

  // ── Save ROI ──
  const handleSave = async () => {
    if (!selectedCam) return;
    setSaving(true);
    const result = await API.saveRoi(selectedCam, roi);
    setSaving(false); setSaveResult(result);
    if (result.ok) setSavedRoi({ ...roi });
  };

  const hasChanges = savedRoi && (
    Math.abs(roi.x1 - savedRoi.x1) > 0.001 || Math.abs(roi.y1 - savedRoi.y1) > 0.001 ||
    Math.abs(roi.x2 - savedRoi.x2) > 0.001 || Math.abs(roi.y2 - savedRoi.y2) > 0.001
  );

  // ── Trigger line crossing detection ──
  useEffect(() => {
    const sideOfLine = (pt) => {
      const { x: ax, y: ay } = triggerLine.p1;
      const { x: bx, y: by } = triggerLine.p2;
      return (bx - ax) * (pt.y - ay) - (by - ay) * (pt.x - ax);
    };

    const now = Date.now();
    const nextState = { ...trackStateRef.current };

    trackedObjects.forEach((obj) => {
      if (!obj || !Array.isArray(obj.bbox)) return;
      const [x1, y1, x2, y2] = obj.bbox;
      // centroid ของ bbox
      const center = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
      const side = sideOfLine(center);
      const key = String(obj.track_id);
      const prev = nextState[key];

      const movedEnough = prev ? Math.hypot(center.x - prev.center.x, center.y - prev.center.y) >= 0.005 : false;
      const crossed = prev && (side * prev.side < 0) && movedEnough;
      const cooldownPassed = !prev?.lastCrossTs || (now - prev.lastCrossTs > 1200);

      if (crossed && cooldownPassed) {
        // Capture frame จาก canvas
        const canvas = canvasRef.current;
        const snapshot = canvas ? canvas.toDataURL("image/jpeg", 0.85) : null;
        if (snapshot) {
          setCapturedTracks((old) => {
            const next = {
              ...old,
              [key]: { track_id: key, ts: new Date().toISOString(), ts_ms: now, image: snapshot },
            };
            const entries = Object.entries(next)
              .sort((a, b) => (b[1].ts_ms || 0) - (a[1].ts_ms || 0))
              .slice(0, MAX_CAPTURED_TRACKS);
            return Object.fromEntries(entries);
          });
        }
        nextState[key] = { side, center, ts: now, lastCrossTs: now };
      } else {
        nextState[key] = { side, center, ts: now, lastCrossTs: prev?.lastCrossTs || 0 };
      }
    });

    // cleanup stale
    for (const k of Object.keys(nextState)) {
      if (now - (nextState[k]?.ts || 0) > 8000) delete nextState[k];
    }
    trackStateRef.current = nextState;
  }, [trackedObjects, triggerLine]);

  // ── Canvas draw loop ──
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Draw video/snapshot source
    const source = streamMode === "live" ? imgRef.current : snapshotImgRef.current;
    const canDraw = source && (
      (source instanceof HTMLImageElement && source.complete && source.naturalWidth > 0) ||
      (source instanceof HTMLVideoElement && source.readyState >= 2)
    );

    if (canDraw) {
      ctx.drawImage(source, 0, 0, W, H);
    } else {
      // Placeholder
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, "#06090f"); grad.addColorStop(0.5, "#0c1220"); grad.addColorStop(1, "#080b14");
      ctx.fillStyle = grad; ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgba(20,31,56,0.8)"; ctx.lineWidth = 1;
      for (let x = 0; x <= W; x += 80) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
      for (let y = 0; y <= H; y += 60) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      ctx.font = "bold 12px monospace"; ctx.fillStyle = "rgba(255,255,255,0.12)";
      ctx.textAlign = "center";
      ctx.fillText(streamMode === "live" ? "Connecting live stream..." : "กด Capture Snapshot", W / 2, H - 18);
      ctx.textAlign = "left";
    }

    // ROI overlay
    const rx1 = roi.x1 * W, ry1 = roi.y1 * H, rx2 = roi.x2 * W, ry2 = roi.y2 * H;
    ctx.fillStyle = "rgba(0,0,0,0.50)";
    ctx.fillRect(0, 0, W, ry1); ctx.fillRect(0, ry2, W, H - ry2);
    ctx.fillRect(0, ry1, rx1, ry2 - ry1); ctx.fillRect(rx2, ry1, W - rx2, ry2 - ry1);
    ctx.fillStyle = "rgba(37,99,235,0.04)"; ctx.fillRect(rx1, ry1, rx2 - rx1, ry2 - ry1);
    ctx.strokeStyle = C.blueBright; ctx.lineWidth = 1.5; ctx.setLineDash([8, 4]);
    ctx.strokeRect(rx1, ry1, rx2 - rx1, ry2 - ry1); ctx.setLineDash([]);

    // Corner handles
    [[rx1, ry1], [rx2, ry1], [rx1, ry2], [rx2, ry2]].forEach(([x, y]) => {
      ctx.fillStyle = "rgba(37,99,235,0.25)"; ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = C.blue; ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
    });
    const mx = rx1 + (rx2 - rx1) / 2, my = ry1 + (ry2 - ry1) / 2;
    [[mx, ry1], [mx, ry2], [rx1, my], [rx2, my]].forEach(([x, y]) => {
      ctx.fillStyle = C.blue; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
    });

    // ROI label
    ctx.font = "bold 11px monospace"; ctx.fillStyle = C.blueBright;
    ctx.fillText("ROI DETECTION ZONE", rx1 + 10, ry1 + 18);
    ctx.font = "10px monospace"; ctx.fillStyle = "rgba(96,165,250,0.65)";
    ctx.fillText(`(${roi.x1.toFixed(2)}, ${roi.y1.toFixed(2)}) → (${roi.x2.toFixed(2)}, ${roi.y2.toFixed(2)})`, rx1 + 10, ry1 + 32);

    // Tracking boxes — แสดง bbox พร้อม centroid
    trackedObjects.forEach((obj) => {
      if (!Array.isArray(obj?.bbox)) return;
      const [x1, y1, x2, y2] = obj.bbox;
      const bx = x1 * W, by = y1 * H, bw = (x2 - x1) * W, bh = (y2 - y1) * H;
      const cx = (x1 + x2) / 2 * W, cy = (y1 + y2) / 2 * H;

      // Bbox
      ctx.strokeStyle = "#f59e0b"; ctx.lineWidth = 2;
      ctx.strokeRect(bx, by, bw, bh);

      // Centroid dot (จุดที่ใช้เช็ค crossing)
      ctx.fillStyle = "#fbbf24";
      ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI * 2); ctx.stroke();

      // Track label
      const label = `TID ${obj.track_id}`;
      ctx.fillStyle = "rgba(245,158,11,0.25)"; ctx.fillRect(bx, Math.max(0, by - 16), label.length * 7 + 8, 14);
      ctx.fillStyle = "#fbbf24"; ctx.font = "bold 10px monospace";
      ctx.fillText(label, bx + 4, Math.max(10, by - 4));

      // ถ้ารอข้ามเส้น → แสดงเส้นประจาก centroid ไปยัง trigger line
      const prev = trackStateRef.current[String(obj.track_id)];
      if (prev) {
        const side = (triggerLine.p2.x - triggerLine.p1.x) * (prev.center.y - triggerLine.p1.y) -
                     (triggerLine.p2.y - triggerLine.p1.y) * (prev.center.x - triggerLine.p1.x);
        const color = side > 0 ? "rgba(34,211,238,0.4)" : "rgba(251,191,36,0.4)";
        ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(cx, cy);
        // project to line
        const lx = ((triggerLine.p1.x + triggerLine.p2.x) / 2) * W;
        const ly = ((triggerLine.p1.y + triggerLine.p2.y) / 2) * H;
        ctx.lineTo(lx, ly); ctx.stroke(); ctx.setLineDash([]);
      }
    });

    // Trigger line
    const l1x = triggerLine.p1.x * W, l1y = triggerLine.p1.y * H;
    const l2x = triggerLine.p2.x * W, l2y = triggerLine.p2.y * H;
    ctx.strokeStyle = C.cyan; ctx.lineWidth = 2.5; ctx.setLineDash([6, 5]);
    ctx.beginPath(); ctx.moveTo(l1x, l1y); ctx.lineTo(l2x, l2y); ctx.stroke(); ctx.setLineDash([]);
    [[l1x, l1y], [l2x, l2y]].forEach(([x, y]) => {
      ctx.fillStyle = "#67e8f9"; ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.stroke();
    });
    ctx.fillStyle = "#67e8f9"; ctx.font = "bold 11px monospace";
    ctx.fillText("TRIGGER LINE", l1x + 10, l1y - 10);

    // Camera + timestamp overlay
    const cam = cameras?.find(c => c.id === selectedCam);
    ctx.font = "bold 10px monospace"; ctx.fillStyle = "rgba(255,255,255,0.28)";
    ctx.fillText(`${cam?.name || selectedCam} [${streamMode.toUpperCase()}]`, 10, 18);
    ctx.textAlign = "right";
    ctx.fillText(new Date().toLocaleTimeString("th-TH", { hour12: false }), W - 10, 18);
    ctx.textAlign = "left";

    // Tracking source badge
    const srcColor = trackingSource === "websocket" ? C.green : trackingSource === "client" ? C.amber : C.dim;
    const srcLabel = trackingSource === "websocket" ? "WS TRACK" : trackingSource === "client" ? "LOCAL TRACK" : "NO TRACK";
    ctx.fillStyle = `${srcColor}22`; ctx.fillRect(W - 100, H - 22, 96, 18);
    ctx.fillStyle = srcColor; ctx.font = "bold 9px monospace";
    ctx.textAlign = "right"; ctx.fillText(srcLabel, W - 6, H - 8); ctx.textAlign = "left";

    // Unsaved changes warning
    if (hasChanges) {
      ctx.fillStyle = "rgba(245,158,11,0.75)"; ctx.font = "bold 10px monospace";
      ctx.textAlign = "right"; ctx.fillText("⚠ UNSAVED CHANGES", W - 10, H - 32); ctx.textAlign = "left";
    }

    if (snapshotLoading) {
      ctx.fillStyle = "rgba(5,8,16,0.7)"; ctx.fillRect(0, 0, W, H);
      ctx.font = "bold 14px monospace"; ctx.fillStyle = C.blueBright; ctx.textAlign = "center";
      ctx.fillText("⏳ Capturing snapshot...", W / 2, H / 2); ctx.textAlign = "left";
    }
  }, [roi, cameras, selectedCam, hasChanges, snapshotLoading, streamMode, trackedObjects, triggerLine, trackingSource]);

  // ── Draw loop ──
  useEffect(() => {
    const interval = setInterval(drawCanvas, streamMode === "live" ? 33 : 100);
    return () => clearInterval(interval);
  }, [drawCanvas, streamMode]);

  // ── Mouse drag ──
  const getHitTarget = useCallback((mx, my) => {
    const W = CANVAS_W, H = CANVAS_H;
    const rx1 = roi.x1 * W, ry1 = roi.y1 * H, rx2 = roi.x2 * W, ry2 = roi.y2 * H;
    const T = 16;
    const corners = [["tl", rx1, ry1], ["tr", rx2, ry1], ["bl", rx1, ry2], ["br", rx2, ry2]];
    for (const [k, x, y] of corners) if (Math.hypot(mx - x, my - y) < T) return k;
    const midX = rx1 + (rx2 - rx1) / 2, midY = ry1 + (ry2 - ry1) / 2;
    const edges = [["t", midX, ry1], ["b", midX, ry2], ["l", rx1, midY], ["r", rx2, midY]];
    for (const [k, x, y] of edges) if (Math.hypot(mx - x, my - y) < T) return k;
    if (mx > rx1 && mx < rx2 && my > ry1 && my < ry2) return "move";
    return null;
  }, [roi]);

  const getLineHit = useCallback((mx, my) => {
    const p1 = { x: triggerLine.p1.x * CANVAS_W, y: triggerLine.p1.y * CANVAS_H };
    const p2 = { x: triggerLine.p2.x * CANVAS_W, y: triggerLine.p2.y * CANVAS_H };
    const T = 14;
    if (Math.hypot(mx - p1.x, my - p1.y) <= T) return "p1";
    if (Math.hypot(mx - p2.x, my - p2.y) <= T) return "p2";
    const vx = p2.x - p1.x, vy = p2.y - p1.y, len2 = vx * vx + vy * vy;
    if (len2 < 1) return null;
    const t = Math.max(0, Math.min(1, ((mx - p1.x) * vx + (my - p1.y) * vy) / len2));
    return Math.hypot(mx - (p1.x + t * vx), my - (p1.y + t * vy)) <= 10 ? "line" : null;
  }, [triggerLine]);

  const CURSOR_MAP = { tl: "nw-resize", tr: "ne-resize", bl: "sw-resize", br: "se-resize", t: "n-resize", b: "s-resize", l: "w-resize", r: "e-resize", move: "grab", p1: "grab", p2: "grab", line: "move" };

  const getPos = (e) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return { mx: 0, my: 0 };
    return { mx: (e.clientX - rect.left) * CANVAS_W / rect.width, my: (e.clientY - rect.top) * CANVAS_H / rect.height };
  };

  const handleMouseDown = (e) => {
    const { mx, my } = getPos(e);
    if (editMode === "trigger") {
      const target = getLineHit(mx, my);
      if (target) setDragging({ target, mode: "trigger", startMx: mx, startMy: my, startLine: { p1: { ...triggerLine.p1 }, p2: { ...triggerLine.p2 } } });
      return;
    }
    const target = getHitTarget(mx, my);
    if (target) setDragging({ target, mode: "roi", startMx: mx, startMy: my, startRoi: { ...roi } });
  };

  const handleMouseMove = (e) => {
    const { mx, my } = getPos(e);
    if (!dragging) {
      const t = editMode === "trigger" ? getLineHit(mx, my) : getHitTarget(mx, my);
      if (canvasRef.current) canvasRef.current.style.cursor = CURSOR_MAP[t] || "default";
      return;
    }
    const cl = (v) => Math.max(0, Math.min(1, v));
    const dx = (mx - dragging.startMx) / CANVAS_W, dy = (my - dragging.startMy) / CANVAS_H;

    if (dragging.mode === "trigger") {
      const s = dragging.startLine;
      if (dragging.target === "p1") setTriggerLine({ ...s, p1: { x: cl(s.p1.x + dx), y: cl(s.p1.y + dy) } });
      else if (dragging.target === "p2") setTriggerLine({ ...s, p2: { x: cl(s.p2.x + dx), y: cl(s.p2.y + dy) } });
      else if (dragging.target === "line") setTriggerLine({ p1: { x: cl(s.p1.x + dx), y: cl(s.p1.y + dy) }, p2: { x: cl(s.p2.x + dx), y: cl(s.p2.y + dy) } });
      return;
    }

    const s = dragging.startRoi;
    let n = { ...roi };
    switch (dragging.target) {
      case "tl": n = { ...n, x1: cl(s.x1 + dx), y1: cl(s.y1 + dy) }; break;
      case "tr": n = { ...n, x2: cl(s.x2 + dx), y1: cl(s.y1 + dy) }; break;
      case "bl": n = { ...n, x1: cl(s.x1 + dx), y2: cl(s.y2 + dy) }; break;
      case "br": n = { ...n, x2: cl(s.x2 + dx), y2: cl(s.y2 + dy) }; break;
      case "t": n = { ...n, y1: cl(s.y1 + dy) }; break;
      case "b": n = { ...n, y2: cl(s.y2 + dy) }; break;
      case "l": n = { ...n, x1: cl(s.x1 + dx) }; break;
      case "r": n = { ...n, x2: cl(s.x2 + dx) }; break;
      case "move": {
        const w = s.x2 - s.x1, h = s.y2 - s.y1;
        let nx1 = cl(s.x1 + dx), ny1 = cl(s.y1 + dy);
        if (nx1 + w > 1) nx1 = 1 - w;
        if (ny1 + h > 1) ny1 = 1 - h;
        n = { x1: nx1, y1: ny1, x2: nx1 + w, y2: ny1 + h };
        break;
      }
    }
    if (n.x2 - n.x1 > 0.05 && n.y2 - n.y1 > 0.05) setRoi(n);
  };

  const handleMouseUp = () => setDragging(null);

  if (!cameras) return (
    <div style={{ background: C.bg, color: C.text, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace" }}>
      <div style={{ textAlign: "center", opacity: 0.6 }}>
        <div style={{ fontSize: 28, marginBottom: 10 }}>📡</div>
        <div>Connecting...</div>
      </div>
    </div>
  );

  const capturedList = Object.values(capturedTracks).sort((a, b) => (b.ts_ms || 0) - (a.ts_ms || 0));

  return (
    <div style={{ background: C.bg, color: C.text, minHeight: "100vh", fontFamily: "'IBM Plex Sans', 'Noto Sans Thai', system-ui, sans-serif" }}>
      {/* HEADER */}
      <div style={{ background: C.card, borderBottom: `1px solid ${C.cardBorder}`, padding: "10px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 30, height: 30, borderRadius: 6, background: `linear-gradient(135deg, ${C.blue}, ${C.purple})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff" }}>R</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.bright, letterSpacing: "-0.02em" }}>
            ROI Agent <span style={{ color: C.dim, fontWeight: 400, fontSize: 12 }}>— Detection Zone Config</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {useMock && <span style={{ fontSize: 10, padding: "3px 9px", borderRadius: 4, background: C.amberDim, color: C.amber, fontWeight: 700 }}>DEMO MODE</span>}
          <span style={{ fontSize: 10, padding: "3px 9px", borderRadius: 4, fontWeight: 700, background: connected ? C.greenDim : C.redDim, color: connected ? C.green : C.red }}>
            {connected ? "● API CONNECTED" : "○ API OFFLINE"}
          </span>
          <span style={{ fontSize: 10, padding: "3px 9px", borderRadius: 4, fontWeight: 700, background: wsConnected ? C.greenDim : "rgba(245,158,11,0.08)", color: wsConnected ? C.green : C.amber }}>
            {wsConnected ? "● TRACKING WS" : "⚡ LOCAL TRACK"}
          </span>
        </div>
      </div>

      <div style={{ display: "flex", minHeight: "calc(100vh - 52px)" }}>
        {/* SIDEBAR */}
        <div style={{ width: 220, background: C.card, borderRight: `1px solid ${C.cardBorder}`, padding: "16px 0", flexShrink: 0, overflowY: "auto" }}>
          <div style={{ padding: "0 16px 10px", fontSize: 10, fontWeight: 700, color: C.dim, textTransform: "uppercase", letterSpacing: "0.1em" }}>CAMERAS</div>
          {cameras.map(cam => (
            <div key={cam.id} onClick={() => setSelectedCam(cam.id)} style={{ padding: "10px 16px", cursor: "pointer", background: selectedCam === cam.id ? C.blueGlow : "transparent", borderLeft: `3px solid ${selectedCam === cam.id ? C.blue : "transparent"}`, transition: "all 0.12s" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot status={cam.status} />
                <span style={{ fontSize: 12, fontWeight: 600, color: selectedCam === cam.id ? C.bright : C.text }}>{cam.name}</span>
              </div>
              <div style={{ fontSize: 9, color: C.dim, marginTop: 3, marginLeft: 15, fontFamily: "monospace" }}>{cam.id} • {cam.status}</div>
            </div>
          ))}
        </div>

        {/* MAIN */}
        <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
          {/* Controls */}
          <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ fontSize: 10, color: C.dim }}>Mode:</span>
              {["live", "snapshot"].map(mode => (
                <button key={mode} onClick={() => setStreamMode(mode)}
                  style={{ padding: "6px 12px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", border: `1px solid ${streamMode === mode ? C.blue : C.cardBorder}`, background: streamMode === mode ? C.blueGlow : "transparent", color: streamMode === mode ? C.blueBright : C.dim }}>
                  {mode === "live" ? "🎥 Live Stream" : "📸 Snapshot"}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 10, color: C.dim }}>Edit:</span>
              {[{ key: "roi", label: "ROI" }, { key: "trigger", label: "Trigger Line" }].map(m => (
                <button key={m.key} onClick={() => setEditMode(m.key)}
                  style={{ padding: "5px 10px", borderRadius: 5, fontSize: 10, fontWeight: 700, border: `1px solid ${editMode === m.key ? C.blue : C.cardBorder}`, background: editMode === m.key ? C.blueGlow : "transparent", color: editMode === m.key ? C.blueBright : C.dim, cursor: "pointer" }}>
                  {m.label}
                </button>
              ))}
            </div>
            {streamMode === "snapshot" && (
              <button onClick={captureSnapshot} disabled={snapshotLoading}
                style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${snapshotLoading ? C.dim : C.blue}`, background: C.blueGlow, color: C.blueBright, fontSize: 12, fontWeight: 700, cursor: snapshotLoading ? "wait" : "pointer" }}>
                {snapshotLoading ? "⏳..." : "📸 Capture"}
              </button>
            )}
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: C.dim }}>Presets:</span>
            {[
              { label: "Toll Booth", roi: { x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 } },
              { label: "Wide", roi: { x1: 0.05, y1: 0.15, x2: 0.95, y2: 0.90 } },
              { label: "Center", roi: { x1: 0.25, y1: 0.35, x2: 0.75, y2: 0.75 } },
              { label: "Full", roi: { x1: 0.0, y1: 0.0, x2: 1.0, y2: 1.0 } },
            ].map(p => (
              <button key={p.label} onClick={() => setRoi(p.roi)}
                style={{ padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600, border: `1px solid ${C.cardBorder}`, background: "transparent", color: C.text, cursor: "pointer" }}>
                {p.label}
              </button>
            ))}
          </div>

          {/* Canvas */}
          <div style={{ position: "relative", marginBottom: 16 }}>
            {streamMode === "live" && streamUrl && (
              <img ref={imgRef} src={streamUrl} style={{ display: "none" }}
                onError={() => setStreamError("Stream unavailable")}
                onLoad={() => setStreamError(null)} alt="" />
            )}
            <canvas ref={canvasRef} width={CANVAS_W} height={CANVAS_H}
              onMouseDown={handleMouseDown} onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}
              style={{ width: "100%", maxWidth: CANVAS_W, display: "block", borderRadius: 8, border: `1px solid ${C.cardBorder}` }} />
            {(snapshotError || streamError) && (
              <div style={{ position: "absolute", bottom: 10, left: "50%", transform: "translateX(-50%)", background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.35)", borderRadius: 6, padding: "5px 12px", fontSize: 10, color: "#fca5a5", fontFamily: "monospace" }}>
                ⚠ {snapshotError || streamError}
              </div>
            )}
          </div>

          {/* Bottom panels */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {/* ROI Coordinates */}
            <div style={{ background: C.card, borderRadius: 8, padding: 16, border: `1px solid ${C.cardBorder}`, flex: "1 1 280px" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em" }}>📐 ROI Coordinates (0.0–1.0)</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {[["x1", "X1 (left)", roi.x1], ["y1", "Y1 (top)", roi.y1], ["x2", "X2 (right)", roi.x2], ["y2", "Y2 (bottom)", roi.y2]].map(([key, label, val]) => (
                  <div key={key}>
                    <div style={{ fontSize: 10, color: C.dim, marginBottom: 4 }}>{label}</div>
                    <input type="number" min={0} max={1} step={0.005} value={parseFloat(val).toFixed(3)}
                      onChange={e => { const v = Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)); setRoi(p => ({ ...p, [key]: v })); }}
                      style={{ width: "100%", padding: "6px 10px", borderRadius: 4, border: `1px solid ${C.cardBorder}`, background: C.bg, color: C.blueBright, fontSize: 13, fontFamily: "monospace", outline: "none" }} />
                  </div>
                ))}
              </div>
            </div>

            {/* Apply to System */}
            <div style={{ background: C.card, borderRadius: 8, padding: 16, border: `1px solid ${hasChanges ? C.amber : C.cardBorder}`, flex: "1 1 280px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em" }}>💾 Apply to System</div>
                <div style={{ fontSize: 12, color: C.text, lineHeight: 1.7, marginBottom: 8 }}>
                  กด <strong>Apply ROI</strong> เพื่อบันทึกค่าลง Redis<br />→ rtsp-producer จะใช้ค่าใหม่ทันที
                </div>
                {hasChanges && <div style={{ padding: "6px 10px", borderRadius: 4, background: C.amberDim, border: `1px solid rgba(245,158,11,0.2)`, fontSize: 11, color: C.amber, marginBottom: 8 }}>⚠ มีค่าที่ยังไม่ได้บันทึก</div>}
                {saveResult && <div style={{ padding: "6px 10px", borderRadius: 4, fontSize: 11, marginBottom: 8, background: saveResult.ok ? C.greenDim : C.redDim, border: `1px solid ${saveResult.ok ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}`, color: saveResult.ok ? C.green : C.red }}>{saveResult.ok ? "✓ " : "✗ "}{saveResult.message}</div>}
              </div>
              <button onClick={handleSave} disabled={saving || !hasChanges}
                style={{ padding: "10px 0", borderRadius: 6, border: "none", fontSize: 13, fontWeight: 700, cursor: saving || !hasChanges ? "not-allowed" : "pointer", background: hasChanges ? C.blue : C.cardBorder, color: hasChanges ? "#fff" : C.dim, opacity: saving ? 0.6 : 1 }}>
                {saving ? "⏳ Saving..." : hasChanges ? "✓ Apply ROI" : "No Changes"}
              </button>
            </div>
          </div>

          {/* Tracking + Captures */}
          <div style={{ marginTop: 16, background: C.card, borderRadius: 8, padding: 14, border: `1px solid ${C.cardBorder}` }}>
            {/* Status bar */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                🚗 Trigger Captures
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{
                  fontSize: 9, padding: "2px 8px", borderRadius: 3, fontWeight: 700,
                  background: trackingSource === "websocket" ? C.greenDim : trackingSource === "client" ? C.amberDim : C.redDim,
                  color: trackingSource === "websocket" ? C.green : trackingSource === "client" ? C.amber : C.red,
                }}>
                  {trackingSource === "websocket" ? "● WS TRACKING" : trackingSource === "client" ? "⚡ CLIENT TRACKING" : "○ NO TRACKING"}
                </span>
                <span style={{ fontSize: 9, color: C.dim }}>
                  {trackedObjects.length > 0 ? `${trackedObjects.length} objects` : "ไม่พบการเคลื่อนไหว"}
                </span>
              </div>

              {/* ── How it works notice ── */}
              <div style={{ marginLeft: "auto", fontSize: 9, color: C.dim, fontStyle: "italic" }}>
                {trackingSource === "client"
                  ? "ตรวจจับการเคลื่อนไหวจาก MJPEG stream โดยตรง — centroid ข้ามเส้น = capture"
                  : trackingSource === "websocket"
                  ? "รับ tracking data จาก WebSocket server"
                  : "รอ stream..."}
              </div>
            </div>

            {/* Active tracks */}
            {trackedObjects.length > 0 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                {trackedObjects.map(obj => {
                  const prev = trackStateRef.current[String(obj.track_id)];
                  const captured = !!capturedTracks[String(obj.track_id)];
                  return (
                    <div key={obj.track_id} style={{ padding: "4px 10px", borderRadius: 4, border: `1px solid ${captured ? "rgba(16,185,129,0.3)" : "rgba(245,158,11,0.3)"}`, background: captured ? "rgba(16,185,129,0.06)" : "rgba(245,158,11,0.06)", fontSize: 10, color: captured ? C.green : C.amber, fontFamily: "monospace" }}>
                      TID {obj.track_id} {captured ? "✓" : "→"}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Captured thumbnails */}
            {capturedList.length === 0 ? (
              <div style={{ color: C.dim, fontSize: 11, padding: "12px 0", textAlign: "center" }}>
                {streamMode !== "live" ? "สลับไป Live Stream เพื่อใช้ trigger" : "รอรถวิ่งข้ามเส้น trigger line..."}
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8 }}>
                {capturedList.map(track => (
                  <div key={track.track_id} style={{ border: `1px solid ${C.cardBorder}`, borderRadius: 6, overflow: "hidden", background: C.bg }}>
                    <img src={track.image} alt="" style={{ width: "100%", height: 80, objectFit: "cover", display: "block" }} />
                    <div style={{ padding: "5px 8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: 10, color: C.green, fontFamily: "monospace", fontWeight: 700 }}>TID {track.track_id}</span>
                      <span style={{ fontSize: 9, color: C.dim }}>{new Date(track.ts).toLocaleTimeString("th-TH", { hour12: false })}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {capturedList.length > 0 && (
              <button onClick={() => setCapturedTracks({})} style={{ marginTop: 10, padding: "5px 12px", borderRadius: 4, border: `1px solid ${C.cardBorder}`, background: "transparent", color: C.dim, fontSize: 10, cursor: "pointer" }}>
                ล้างทั้งหมด ({capturedList.length})
              </button>
            )}
          </div>

          {/* Tips */}
          <div style={{ marginTop: 14, padding: 14, borderRadius: 8, background: C.card, border: `1px solid ${C.cardBorder}` }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>💡 How Trigger Works</div>
            <div style={{ fontSize: 11, color: C.dim, lineHeight: 2.0 }}>
              • <strong style={{ color: C.text }}>Centroid crossing:</strong> ใช้จุดกลาง (cx, cy) ของ bounding box — ไม่ต้องรอทั้งคันข้าม<br />
              • <strong style={{ color: C.text }}>Client tracking:</strong> ถ้าไม่มี WebSocket → ตรวจ motion จาก MJPEG frame โดยตรง (frame diff)<br />
              • <strong style={{ color: C.amber }}>⚡ LOCAL TRACK</strong> = client-side &nbsp;|&nbsp; <strong style={{ color: C.green }}>● WS TRACK</strong> = server tracking (แม่นยำกว่า)<br />
              • ลาก <strong style={{ color: C.cyan }}>Trigger Line</strong> ไปวางในตำแหน่งที่รถจะผ่าน (เส้นสีฟ้า)<br />
              • Capture ทำ <strong style={{ color: C.text }}>1 ครั้งต่อ Track ID</strong> พร้อม cooldown 1.2s
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}