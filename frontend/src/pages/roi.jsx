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

// ─── API FUNCTIONS ───────────────────────────────────────────
function normalizeCamera(cam) {
  if (!cam || typeof cam !== "object") return null;
  const id = cam.id || cam.camera_id;
  if (!id) return null;
  return {
    ...cam,
    id,
    name: cam.name || id,
    status: cam.status || "unknown",
  };
}

async function fetchCameras() {
  try {
    const res = await fetch(`${API_BASE}/api/roi-agent/cameras`);
    if (!res.ok) throw new Error(`${res.status}`);
    const raw = await res.json();
    if (!Array.isArray(raw)) return null;
    return raw.map(normalizeCamera).filter(Boolean);
  } catch (e) {
    console.warn("fetchCameras failed:", e);
    return null;
  }
}

async function fetchSnapshot(cameraId) {
  const res = await fetch(
    `${API_BASE}/api/roi-agent/snapshot/${cameraId}?width=1280&t=${Date.now()}`
  );
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const json = await res.json();
      detail = json.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

async function fetchRoi(cameraId) {
  try {
    const res = await fetch(`${API_BASE}/api/roi-agent/config/${cameraId}`);
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("fetchRoi failed:", e);
    return null;
  }
}

async function fetchRecentActivity(cameraId, limit = 50) {
  try {
    const params = new URLSearchParams({ limit: String(limit), camera_id: cameraId });
    const res = await fetch(`${API_BASE}/api/reports/activity?${params.toString()}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch (e) {
    console.warn("fetchRecentActivity failed:", e);
    return [];
  }
}

async function saveRoi(cameraId, roi) {
  try {
    const res = await fetch(`${API_BASE}/api/roi-agent/config/${cameraId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(roi),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `${res.status}`);
    }
    return await res.json();
  } catch (e) {
    console.warn("saveRoi failed:", e);
    return { ok: false, message: e.message };
  }
}

// ─── DESIGN TOKENS ───────────────────────────────────────────
const C = {
  bg: "#050810",
  card: "#0a1020",
  cardBorder: "#141f38",
  cardBorderActive: "#1e3a6e",
  text: "#a8bdd4",
  dim: "#3d5070",
  bright: "#e8f0f8",
  blue: "#2563eb",
  blueBright: "#3b82f6",
  blueGlow: "rgba(37,99,235,0.10)",
  green: "#10b981",
  greenDim: "rgba(16,185,129,0.08)",
  red: "#ef4444",
  redDim: "rgba(239,68,68,0.08)",
  amber: "#f59e0b",
  amberDim: "rgba(245,158,11,0.08)",
  purple: "#7c3aed",
};

// ─── MOCK DATA ────────────────────────────────────────────────
const MOCK_CAMERAS = [
  { id: "PCN_Lane4", name: "PCN-MM04 Lane 4", status: "no_heartbeat", roi: { x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 } },
  { id: "PCN_Lane5", name: "PCN-MM04 Lane 5", status: "no_heartbeat", roi: null },
  { id: "PCN_Lane6", name: "PCN-MM04 Lane 6", status: "no_heartbeat", roi: null },
];

// ─── STATUS DOT ───────────────────────────────────────────────
function StatusDot({ status }) {
  const color =
    status === "online" ? C.green :
    status === "stale" ? C.amber :
    status === "offline" ? C.red : C.dim;
  const glow = status === "online" ? `0 0 6px ${C.green}` : "none";
  return (
    <span style={{
      display: "inline-block", width: 7, height: 7, borderRadius: "50%",
      background: color, boxShadow: glow, flexShrink: 0,
    }} />
  );
}

// ─── SNAPSHOT ERROR BADGE ─────────────────────────────────────
function SnapshotError({ message }) {
  return (
    <div style={{
      position: "absolute", bottom: 10, left: "50%", transform: "translateX(-50%)",
      background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.35)",
      borderRadius: 6, padding: "5px 12px", fontSize: 10, color: "#fca5a5",
      fontFamily: "monospace", whiteSpace: "nowrap", pointerEvents: "none",
      backdropFilter: "blur(4px)", maxWidth: "90%", textOverflow: "ellipsis", overflow: "hidden",
    }}>
      ⚠ {message}
    </div>
  );
}

// ─── MAIN COMPONENT ──────────────────────────────────────────
export default function ROIDashboard() {
  const [cameras, setCameras] = useState(null);
  const [selectedCam, setSelectedCam] = useState(null);
  const [streamMode, setStreamMode] = useState("live"); // "live" or "snapshot"
  const [snapshotUrl, setSnapshotUrl] = useState(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState(null);
  const [streamError, setStreamError] = useState(null);
  const [roi, setRoi] = useState({ x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 });
  const [savedRoi, setSavedRoi] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [useMock, setUseMock] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState(null);
  const [connected, setConnected] = useState(false);
  const [trackedObjects, setTrackedObjects] = useState([]);
  const [triggerLine, setTriggerLine] = useState({ p1: { x: 0.20, y: 0.76 }, p2: { x: 0.88, y: 0.76 } });
  const [editMode, setEditMode] = useState("roi"); // roi | trigger
  const [capturedTracks, setCapturedTracks] = useState({});
  const [wsConnected, setWsConnected] = useState(false);
  const trackStateRef = useRef({});

  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const videoRef = useRef(null);
  const [dragging, setDragging] = useState(null);
  const CANVAS_W = 960, CANVAS_H = 540;

  const isDrawableSourceReady = useCallback((source) => {
    if (!source) return false;
    if (typeof source.readyState === "number") return source.readyState >= 2;
    if (typeof source.complete === "boolean") return source.complete && source.naturalWidth > 0;
    if (typeof source.videoWidth === "number") return source.videoWidth > 0;
    return false;
  }, []);

  // ── MJPEG Stream URL (direct RTSP via ffmpeg) ──
  const streamUrl = selectedCam && ENABLE_MJPEG_STREAM
    ? `${API_BASE}/api/roi-agent/live/${encodeURIComponent(selectedCam)}/mjpeg`
    : null;

  // ── Load cameras on mount ──
  useEffect(() => {
    (async () => {
      const data = await fetchCameras();
      if (data && data.length > 0) {
        setCameras(data);
        setSelectedCam(data[0].id);
        if (data[0].roi) setRoi(data[0].roi);
        setConnected(true);
      } else {
        setUseMock(true);
        setConnected(false);
        setCameras(MOCK_CAMERAS);
        setSelectedCam(MOCK_CAMERAS[0].id);
        if (MOCK_CAMERAS[0].roi) setRoi(MOCK_CAMERAS[0].roi);
      }
    })();
  }, []);

  // ── Load ROI when camera changes ──
  useEffect(() => {
    if (!selectedCam) return;
    imgRef.current = null;
    videoRef.current = null;
    setSnapshotUrl(prev => { if (prev) URL.revokeObjectURL(prev); return null; });
    setSnapshotError(null);
    setStreamError(null);
    setSaveResult(null);
    setTrackedObjects([]);
    setCapturedTracks({});
    setWsConnected(false);
    trackStateRef.current = {};
    (async () => {
      const data = await fetchRoi(selectedCam);
      if (data) { setRoi(data); setSavedRoi(data); }
    })();
  }, [selectedCam]);


  // ── Tracking stream via WebSocket (track_id based) ──
  useEffect(() => {
    if (!selectedCam || !WS_BASE) return;

    const wsUrl = `${WS_BASE}/ws/cameras/${encodeURIComponent(selectedCam)}`;
    let ws = null;
    let active = true;
    let reconnectTimer = null;

    const connect = () => {
      if (!active) return;
      try {
        ws = new WebSocket(wsUrl);
      } catch (_) {
        reconnectTimer = setTimeout(connect, 2000);
        return;
      }

      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => {
        setWsConnected(false);
        if (active) reconnectTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => {
        setWsConnected(false);
      };
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg?.camera_id === selectedCam && Array.isArray(msg.objects)) {
            const cleaned = msg.objects.filter((obj) =>
              obj && typeof obj.track_id !== "undefined" && Array.isArray(obj.bbox) && obj.bbox.length === 4
            );
            setTrackedObjects(cleaned);
          }
        } catch (_) {}
      };
    };

    const bootTimer = setTimeout(connect, 150);

    return () => {
      active = false;
      clearTimeout(bootTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [selectedCam]);

  const captureRawFrame = useCallback(() => {
    const source = streamMode === "live" ? videoRef.current : imgRef.current;
    if (!source) return null;

    const canvas = document.createElement("canvas");
    canvas.width = CANVAS_W;
    canvas.height = CANVAS_H;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    const canDrawVideo =
      source instanceof HTMLVideoElement && source.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA;
    const canDrawImage = source instanceof HTMLImageElement && source.complete;
    if (!canDrawVideo && !canDrawImage) return null;

    ctx.drawImage(source, 0, 0, CANVAS_W, CANVAS_H);
    return canvas.toDataURL("image/jpeg", 0.9);
  }, [streamMode]);

  // ── Trigger capture by line crossing (one shot per track_id) ──
  useEffect(() => {
    if (streamMode !== "live") return;

    const sideOfLine = (pt) => {
      const ax = triggerLine.p1.x, ay = triggerLine.p1.y;
      const bx = triggerLine.p2.x, by = triggerLine.p2.y;
      return (bx - ax) * (pt.y - ay) - (by - ay) * (pt.x - ax);
    };

    const now = Date.now();
    const nextTrackState = { ...trackStateRef.current };

    trackedObjects.forEach((obj) => {
      if (!obj || typeof obj.track_id === "undefined" || !Array.isArray(obj.bbox)) return;
      const [x1, y1, x2, y2] = obj.bbox;
      const center = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
      const side = sideOfLine(center);
      const key = String(obj.track_id);
      const prev = nextTrackState[key];

      const movedEnough = prev ? Math.hypot(center.x - prev.center.x, center.y - prev.center.y) >= 0.01 : false;
      const crossed = prev && side * prev.side < 0 && movedEnough;
      const cooldownPassed = !prev?.lastCrossTs || now - prev.lastCrossTs > 1500;

      if (crossed && cooldownPassed) {
        setCapturedTracks((old) => {
          if (old[key]) return old;
          const snapshot = captureRawFrame();
          const next = {
            ...old,
            [key]: {
              track_id: key,
              ts: new Date().toISOString(),
              ts_ms: now,
              image: snapshot,
            },
          };
          const entries = Object.entries(next)
            .sort((a, b) => (b[1].ts_ms || 0) - (a[1].ts_ms || 0))
            .slice(0, MAX_CAPTURED_TRACKS);
          return Object.fromEntries(entries);
        });
        nextTrackState[key] = { side, center, ts: now, lastCrossTs: now };
      } else {
        nextTrackState[key] = { side, center, ts: now, lastCrossTs: prev?.lastCrossTs || 0 };
      }
    });

    Object.keys(nextTrackState).forEach((k) => {
      if (now - (nextTrackState[k]?.ts || 0) > 10000) delete nextTrackState[k];
    });

    trackStateRef.current = nextTrackState;
  }, [trackedObjects, triggerLine, streamMode, captureRawFrame]);

// ── Poll latest car IDs and keep first snapshot per ID ──
  useEffect(() => {
    if (!selectedCam) return;

    let active = true;
    const poll = async () => {
      const rows = await fetchRecentActivity(selectedCam, 100);
      if (!active) return;

      const normalized = rows
        .filter((r) => r?.camera_id === selectedCam)
        .map((r) => ({
          id: String(r.id),
          plate: r.plate_text || "UNKNOWN",
          confidence: Number(r.confidence || 0),
          created_at: r.created_at,
          crop_url: r.crop_url || null,
        }));

      setRecentCars(normalized.slice(0, 20));

      setCapturedCars((prev) => {
        const next = { ...prev };
        for (const row of normalized) {
          if (!seenCarIdsRef.current.has(row.id) && row.crop_url) {
            seenCarIdsRef.current.add(row.id);
            next[row.id] = row;
          }
        }
        return next;
      });
    };

    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedCam]);

  // ── Handle video stream errors ──
  useEffect(() => {
    const video = videoRef.current;
    if (!video || streamMode !== "live") return;

    const handleError = () => {
      setStreamError("Stream not available. Camera may be offline or RTSP not started.");
    };

    const handleLoad = () => {
      setStreamError(null);
    };

    video.addEventListener("error", handleError);
    video.addEventListener("load", handleLoad);

    return () => {
      video.removeEventListener("error", handleError);
      video.removeEventListener("load", handleLoad);
    };
  }, [streamMode, streamUrl]);

  // ── Capture snapshot ──
  const captureSnapshot = useCallback(async () => {
    if (!selectedCam) return;
    setSnapshotLoading(true);
    setSnapshotError(null);
    try {
      const url = await fetchSnapshot(selectedCam);
      if (snapshotUrl) URL.revokeObjectURL(snapshotUrl);
      setSnapshotUrl(url);
    } catch (e) {
      setSnapshotError(e.message);
    } finally {
      setSnapshotLoading(false);
    }
  }, [selectedCam, snapshotUrl]);

  // ── Auto-refresh (only for snapshot mode) ──
  useEffect(() => {
    if (!refreshInterval || streamMode !== "snapshot") return;
    const timer = setInterval(captureSnapshot, refreshInterval * 1000);
    return () => clearInterval(timer);
  }, [refreshInterval, captureSnapshot, streamMode]);

  // ── Save ROI ──
  const handleSave = async () => {
    if (!selectedCam) return;
    setSaving(true);
    const result = await saveRoi(selectedCam, roi);
    setSaving(false);
    setSaveResult(result);
    if (result.ok) setSavedRoi({ ...roi });
  };

  const hasChanges = savedRoi && (
    Math.abs(roi.x1 - savedRoi.x1) > 0.001 ||
    Math.abs(roi.y1 - savedRoi.y1) > 0.001 ||
    Math.abs(roi.x2 - savedRoi.x2) > 0.001 ||
    Math.abs(roi.y2 - savedRoi.y2) > 0.001
  );

  // ── Canvas drawing ──
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Draw video or image source
    const source = streamMode === "live" ? videoRef.current : imgRef.current;
    const canDrawVideo =
      source instanceof HTMLVideoElement && source.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA;
    const canDrawImage = source instanceof HTMLImageElement && source.complete;

    if (canDrawVideo || canDrawImage) {
      ctx.drawImage(source, 0, 0, W, H);
    } else {
      // Placeholder scene
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, "#06090f");
      grad.addColorStop(0.5, "#0c1220");
      grad.addColorStop(1, "#080b14");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, W, H);

      // Grid lines
      ctx.strokeStyle = "rgba(20,31,56,0.8)";
      ctx.lineWidth = 1;
      for (let x = 0; x <= W; x += 80) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
      for (let y = 0; y <= H; y += 60) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

      // Lane dividers
      ctx.strokeStyle = "rgba(37,99,235,0.12)";
      ctx.lineWidth = 2;
      ctx.setLineDash([20, 30]);
      for (let i = 1; i <= 2; i++) {
        ctx.beginPath();
        ctx.moveTo(W * i / 3, H * 0.1);
        ctx.lineTo(W * i / 3, H);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // No-feed label
      ctx.font = "bold 13px 'JetBrains Mono', monospace";
      ctx.fillStyle = "rgba(255,255,255,0.10)";
      ctx.textAlign = "center";
      const modeText = streamMode === "live" ? "กำลังเชื่อมต่อ live stream..." : "กด Capture Snapshot";
      ctx.fillText(modeText, W / 2, H - 18);
      ctx.textAlign = "left";
    }

    // Dim outside ROI
    const rx1 = roi.x1 * W, ry1 = roi.y1 * H, rx2 = roi.x2 * W, ry2 = roi.y2 * H;
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    ctx.fillRect(0, 0, W, ry1);
    ctx.fillRect(0, ry2, W, H - ry2);
    ctx.fillRect(0, ry1, rx1, ry2 - ry1);
    ctx.fillRect(rx2, ry1, W - rx2, ry2 - ry1);

    // ROI fill
    ctx.fillStyle = "rgba(37,99,235,0.05)";
    ctx.fillRect(rx1, ry1, rx2 - rx1, ry2 - ry1);

    // ROI border
    ctx.strokeStyle = C.blueBright;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([8, 4]);
    ctx.strokeRect(rx1, ry1, rx2 - rx1, ry2 - ry1);
    ctx.setLineDash([]);

    // Corner handles
    [[rx1, ry1], [rx2, ry1], [rx1, ry2], [rx2, ry2]].forEach(([x, y]) => {
      ctx.fillStyle = "rgba(37,99,235,0.25)";
      ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = C.blue;
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
    });

    // Edge midpoints
    const mx = rx1 + (rx2 - rx1) / 2, my = ry1 + (ry2 - ry1) / 2;
    [[mx, ry1], [mx, ry2], [rx1, my], [rx2, my]].forEach(([x, y]) => {
      ctx.fillStyle = C.blue;
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
    });

    // ROI label
    ctx.font = "bold 11px 'JetBrains Mono', monospace";
    ctx.fillStyle = C.blueBright;
    ctx.fillText("ROI DETECTION ZONE", rx1 + 10, ry1 + 18);
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.fillStyle = "rgba(96,165,250,0.65)";
    ctx.fillText(`(${roi.x1.toFixed(2)}, ${roi.y1.toFixed(2)}) → (${roi.x2.toFixed(2)}, ${roi.y2.toFixed(2)})`, rx1 + 10, ry1 + 32);
    ctx.fillText(`${((roi.x2 - roi.x1) * 100).toFixed(0)}% × ${((roi.y2 - roi.y1) * 100).toFixed(0)}% of frame`, rx1 + 10, ry1 + 44);

    // Camera name + time + mode overlay
    const cam = cameras?.find(c => c.id === selectedCam);
    ctx.font = "bold 10px 'JetBrains Mono', monospace";
    ctx.fillStyle = "rgba(255,255,255,0.30)";
    ctx.fillText(`● ${cam?.name || selectedCam} [${streamMode.toUpperCase()}]`, 10, 18);
    const now = new Date().toLocaleTimeString("th-TH", { hour12: false });
    ctx.textAlign = "right";
    ctx.fillText(now, W - 10, 18);
    ctx.textAlign = "left";

    // Tracking boxes + track IDs
    trackedObjects.forEach((obj) => {
      if (!Array.isArray(obj?.bbox)) return;
      const [x1, y1, x2, y2] = obj.bbox;
      const bx = x1 * W, by = y1 * H, bw = (x2 - x1) * W, bh = (y2 - y1) * H;
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 2;
      ctx.strokeRect(bx, by, bw, bh);
      const label = `TID ${obj.track_id}`;
      ctx.fillStyle = "rgba(245,158,11,0.2)";
      ctx.fillRect(bx, Math.max(0, by - 14), 70, 12);
      ctx.fillStyle = "#fbbf24";
      ctx.font = "bold 10px 'JetBrains Mono', monospace";
      ctx.fillText(label, bx + 4, Math.max(10, by - 4));
    });

    // Trigger line overlay
    const l1x = triggerLine.p1.x * W, l1y = triggerLine.p1.y * H;
    const l2x = triggerLine.p2.x * W, l2y = triggerLine.p2.y * H;
    ctx.strokeStyle = "#22d3ee";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(l1x, l1y);
    ctx.lineTo(l2x, l2y);
    ctx.stroke();
    ctx.setLineDash([]);
    [ [l1x, l1y], [l2x, l2y] ].forEach(([x,y]) => {
      ctx.fillStyle = "#67e8f9";
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.fillStyle = "#67e8f9";
    ctx.font = "bold 10px 'JetBrains Mono', monospace";
    ctx.fillText("TRIGGER LINE", l1x + 8, l1y - 8);

    // Car IDs overlay
    const hotCars = recentCars.slice(0, 4);
    if (hotCars.length > 0) {
      ctx.font = "bold 10px 'JetBrains Mono', monospace";
      hotCars.forEach((car, idx) => {
        const txt = `CAR ${car.id} · ${car.plate}`;
        const y = 34 + idx * 14;
        ctx.fillStyle = "rgba(37,99,235,0.14)";
        ctx.fillRect(8, y - 10, Math.min(W - 16, txt.length * 7.5 + 10), 12);
        ctx.fillStyle = "#93c5fd";
        ctx.fillText(txt, 12, y);
      });
    }

    // Unsaved changes warning
    if (hasChanges) {
      ctx.fillStyle = "rgba(245,158,11,0.75)";
      ctx.font = "bold 10px 'JetBrains Mono', monospace";
      ctx.textAlign = "right";
      ctx.fillText("⚠ UNSAVED CHANGES", W - 10, H - 12);
      ctx.textAlign = "left";
    }

    // Loading overlay
    if (snapshotLoading) {
      ctx.fillStyle = "rgba(5,8,16,0.7)";
      ctx.fillRect(0, 0, W, H);
      ctx.font = "bold 14px 'JetBrains Mono', monospace";
      ctx.fillStyle = C.blueBright;
      ctx.textAlign = "center";
      ctx.fillText("⏳ Capturing snapshot...", W / 2, H / 2);
      ctx.textAlign = "left";
    }
  }, [roi, cameras, selectedCam, hasChanges, snapshotLoading, streamMode, isDrawableSourceReady, trackedObjects, triggerLine]);

  useEffect(() => {
    const interval = setInterval(drawCanvas, streamMode === "live" ? 33 : 100); // 30fps for live, 10fps for snapshot
    return () => clearInterval(interval);
  }, [drawCanvas, streamMode]);

  useEffect(() => {
    if (!snapshotUrl || streamMode !== "snapshot") return;
    const img = new Image();
    img.onload = () => { imgRef.current = img; };
    img.src = snapshotUrl;
  }, [snapshotUrl, streamMode]);

  // ── Mouse handlers  ──
  const getHitTarget = useCallback((mx, my) => {
    const W = CANVAS_W, H = CANVAS_H;
    const rx1 = roi.x1 * W, ry1 = roi.y1 * H, rx2 = roi.x2 * W, ry2 = roi.y2 * H;
    const T = 16;
    const corners = [
      { key: "tl", x: rx1, y: ry1 }, { key: "tr", x: rx2, y: ry1 },
      { key: "bl", x: rx1, y: ry2 }, { key: "br", x: rx2, y: ry2 },
    ];
    for (const c of corners) {
      if (Math.hypot(mx - c.x, my - c.y) < T) return c.key;
    }
    const midX = rx1 + (rx2 - rx1) / 2, midY = ry1 + (ry2 - ry1) / 2;
    const edges = [
      { key: "t", x: midX, y: ry1 }, { key: "b", x: midX, y: ry2 },
      { key: "l", x: rx1, y: midY }, { key: "r", x: rx2, y: midY },
    ];
    for (const e of edges) {
      if (Math.hypot(mx - e.x, my - e.y) < T) return e.key;
    }
    if (mx > rx1 && mx < rx2 && my > ry1 && my < ry2) return "move";
    return null;
  }, [roi]);

  const CURSOR_MAP = {
    tl: "nw-resize", tr: "ne-resize", bl: "sw-resize", br: "se-resize",
    t: "n-resize", b: "s-resize", l: "w-resize", r: "e-resize", move: "grab",
    p1: "grab", p2: "grab", line: "move"
  };

    const getLineHitTarget = useCallback((mx, my) => {
    const p1 = { x: triggerLine.p1.x * CANVAS_W, y: triggerLine.p1.y * CANVAS_H };
    const p2 = { x: triggerLine.p2.x * CANVAS_W, y: triggerLine.p2.y * CANVAS_H };
    const T = 14;
    if (Math.hypot(mx - p1.x, my - p1.y) <= T) return "p1";
    if (Math.hypot(mx - p2.x, my - p2.y) <= T) return "p2";

    const vx = p2.x - p1.x;
    const vy = p2.y - p1.y;
    const len2 = vx * vx + vy * vy;
    if (len2 < 1) return null;
    const t = Math.max(0, Math.min(1, ((mx - p1.x) * vx + (my - p1.y) * vy) / len2));
    const px = p1.x + t * vx, py = p1.y + t * vy;
    const d = Math.hypot(mx - px, my - py);
    return d <= 10 ? "line" : null;
  }, [triggerLine]);

  const getEventPos = (e) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return { mx: 0, my: 0 };
    const scaleX = CANVAS_W / rect.width, scaleY = CANVAS_H / rect.height;
    return { mx: (e.clientX - rect.left) * scaleX, my: (e.clientY - rect.top) * scaleY };
  };

  const handleMouseDown = (e) => {
    const { mx, my } = getEventPos(e);
        if (editMode === "trigger") {
      const target = getLineHitTarget(mx, my);
      if (target) {
        setDragging({ target, mode: "trigger", startMx: mx, startMy: my, startLine: { ...triggerLine, p1: { ...triggerLine.p1 }, p2: { ...triggerLine.p2 } } });
      }
      return;
    }

    const target = getHitTarget(mx, my);
    if (target) setDragging({ target, mode: "roi", startMx: mx, startMy: my, startRoi: { ...roi } });
  };

  const handleMouseMove = (e) => {
    const { mx, my } = getEventPos(e);
    if (!dragging) {
            const target = editMode === "trigger" ? getLineHitTarget(mx, my) : getHitTarget(mx, my);
      if (canvasRef.current) canvasRef.current.style.cursor = CURSOR_MAP[target] || (editMode === "trigger" ? "default" : "crosshair");
      return;
    }

    const cl = (v) => Math.max(0, Math.min(1, v));

    if (dragging.mode === "trigger") {
      const dx = (mx - dragging.startMx) / CANVAS_W;
      const dy = (my - dragging.startMy) / CANVAS_H;
      const s = dragging.startLine;
      if (dragging.target === "p1") {
        setTriggerLine({ ...s, p1: { x: cl(s.p1.x + dx), y: cl(s.p1.y + dy) } });
      } else if (dragging.target === "p2") {
        setTriggerLine({ ...s, p2: { x: cl(s.p2.x + dx), y: cl(s.p2.y + dy) } });
      } else if (dragging.target === "line") {
        const nx1 = cl(s.p1.x + dx), ny1 = cl(s.p1.y + dy);
        const nx2 = cl(s.p2.x + dx), ny2 = cl(s.p2.y + dy);
        setTriggerLine({ p1: { x: nx1, y: ny1 }, p2: { x: nx2, y: ny2 } });
      }
      return;
    }
    const dx = (mx - dragging.startMx) / CANVAS_W;
    const dy = (my - dragging.startMy) / CANVAS_H;
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

  // ── Loading screen ──
  if (!cameras) {
    return (
      <div style={{ background: C.bg, color: C.text, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace" }}>
        <div style={{ textAlign: "center", opacity: 0.6 }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>📡</div>
          <div style={{ fontSize: 13 }}>Connecting to ALPR system...</div>
        </div>
      </div>
    );
  }

  const currentCam = cameras.find(c => c.id === selectedCam);

  return (
    <div style={{
      background: C.bg, color: C.text, minHeight: "100vh",
      fontFamily: "'IBM Plex Sans', 'Noto Sans Thai', system-ui, sans-serif",
    }}>
      {/* ── HEADER ── */}
      <div style={{
        background: C.card, borderBottom: `1px solid ${C.cardBorder}`,
        padding: "10px 20px", display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 6,
            background: `linear-gradient(135deg, ${C.blue}, ${C.purple})`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, fontWeight: 800, color: "#fff",
          }}>R</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.bright, letterSpacing: "-0.02em" }}>
            ROI Agent{" "}
            <span style={{ color: C.dim, fontWeight: 400, fontSize: 12 }}>— Detection Zone Config</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {useMock && (
            <span style={{ fontSize: 10, padding: "3px 9px", borderRadius: 4, background: C.amberDim, color: C.amber, fontWeight: 700, letterSpacing: "0.04em" }}>
              DEMO MODE
            </span>
          )}
          <span style={{
            fontSize: 10, padding: "3px 9px", borderRadius: 4, fontWeight: 700, letterSpacing: "0.04em",
            background: connected ? C.greenDim : C.redDim,
            color: connected ? C.green : C.red,
          }}>
            {connected ? "● API CONNECTED" : "○ API OFFLINE"}
          </span>
          <span style={{
            fontSize: 10, padding: "3px 9px", borderRadius: 4, fontWeight: 700, letterSpacing: "0.04em",
            background: wsConnected ? C.greenDim : C.redDim,
            color: wsConnected ? C.green : C.red,
          }}>
            {wsConnected ? "● TRACKING WS" : "○ TRACKING WS"}
          </span>
        </div>
      </div>

      <div style={{ display: "flex", minHeight: "calc(100vh - 52px)" }}>
        {/* ── SIDEBAR ── */}
        <div style={{
          width: 220, background: C.card, borderRight: `1px solid ${C.cardBorder}`,
          padding: "16px 0", flexShrink: 0, overflowY: "auto",
        }}>
          <div style={{ padding: "0 16px 10px", fontSize: 10, fontWeight: 700, color: C.dim, textTransform: "uppercase", letterSpacing: "0.1em" }}>
            Cameras
          </div>
          {cameras.map(cam => (
            <div key={cam.id} onClick={() => setSelectedCam(cam.id)} style={{
              padding: "10px 16px", cursor: "pointer",
              background: selectedCam === cam.id ? C.blueGlow : "transparent",
              borderLeft: `3px solid ${selectedCam === cam.id ? C.blue : "transparent"}`,
              transition: "all 0.12s",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot status={cam.status} />
                <span style={{ fontSize: 12, fontWeight: 600, color: selectedCam === cam.id ? C.bright : C.text }}>
                  {cam.name}
                </span>
              </div>
              <div style={{ fontSize: 9, color: C.dim, marginTop: 3, marginLeft: 15, fontFamily: "monospace" }}>
                {cam.id} • {cam.status}
              </div>
            </div>
          ))}
        </div>

        {/* ── MAIN ── */}
        <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
          {/* Stream mode toggle + controls */}
          <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
            {/* Stream Mode Toggle */}
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ fontSize: 10, color: C.dim }}>Mode:</span>
              {["live", "snapshot"].map(mode => (
                <button 
                  key={mode} 
                  onClick={() => setStreamMode(mode)} 
                  disabled={mode === "live" && !ENABLE_MJPEG_STREAM}
                  style={{
                    padding: "6px 12px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer",
                    border: `1px solid ${streamMode === mode ? C.blue : C.cardBorder}`,
                    background: streamMode === mode ? C.blueGlow : "transparent",
                    color: streamMode === mode ? C.blueBright : C.dim,
                    opacity: mode === "live" && !ENABLE_MJPEG_STREAM ? 0.5 : 1,
                  }}
                >
                  {mode === "live" ? "🎥 Live Stream" : "📸 Snapshot"}
                </button>
              ))}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 10, color: C.dim }}>Edit:</span>
              {[{ key: "roi", label: "ROI" }, { key: "trigger", label: "Trigger Line" }].map(m => (
                <button key={m.key} onClick={() => setEditMode(m.key)} style={{
                  padding: "5px 10px", borderRadius: 5, fontSize: 10, fontWeight: 700,
                  border: `1px solid ${editMode === m.key ? C.blue : C.cardBorder}`,
                  background: editMode === m.key ? C.blueGlow : "transparent",
                  color: editMode === m.key ? C.blueBright : C.dim,
                  cursor: "pointer"
                }}>{m.label}</button>
              ))}
            </div>

            {streamMode === "snapshot" && (
              <>
                <button onClick={captureSnapshot} disabled={snapshotLoading} style={{
                  padding: "7px 14px", borderRadius: 6,
                  border: `1px solid ${snapshotLoading ? C.dim : C.blue}`,
                  background: snapshotLoading ? "transparent" : C.blueGlow,
                  color: snapshotLoading ? C.dim : C.blueBright,
                  fontSize: 12, fontWeight: 700, cursor: snapshotLoading ? "wait" : "pointer",
                  display: "flex", alignItems: "center", gap: 6,
                }}>
                  {snapshotLoading ? "⏳ Capturing..." : "📸 Capture"}
                </button>

                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{ fontSize: 10, color: C.dim }}>Auto-refresh:</span>
                  {[null, 5, 10, 30].map(sec => (
                    <button key={sec ?? "off"} onClick={() => setRefreshInterval(sec)} style={{
                      padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer",
                      border: `1px solid ${refreshInterval === sec ? C.blue : C.cardBorder}`,
                      background: refreshInterval === sec ? C.blueGlow : "transparent",
                      color: refreshInterval === sec ? C.blueBright : C.dim,
                    }}>
                      {sec ? `${sec}s` : "Off"}
                    </button>
                  ))}
                </div>
              </>
            )}

            <div style={{ flex: 1 }} />

            <span style={{ fontSize: 10, color: C.dim, alignSelf: "center" }}>Presets:</span>
            {[
              { label: "Toll Booth", roi: { x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 } },
              { label: "Wide", roi: { x1: 0.05, y1: 0.15, x2: 0.95, y2: 0.90 } },
              { label: "Center", roi: { x1: 0.25, y1: 0.35, x2: 0.75, y2: 0.75 } },
              { label: "Full", roi: { x1: 0.0, y1: 0.0, x2: 1.0, y2: 1.0 } },
            ].map(p => (
              <button key={p.label} onClick={() => setRoi(p.roi)} style={{
                padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600,
                border: `1px solid ${C.cardBorder}`, background: "transparent",
                color: C.text, cursor: "pointer",
              }}>
                {p.label}
              </button>
            ))}
          </div>

          {/* Canvas + video/snapshot + errors */}
          <div style={{ position: "relative", marginBottom: 16 }}>
            {/* Hidden video element for live stream */}
            {streamMode === "live" && streamUrl && (
              <img
                ref={videoRef}
                src={streamUrl}
                style={{ display: "none" }}
                alt="Live stream"
              />
            )}

            <canvas
              ref={canvasRef}
              width={CANVAS_W}
              height={CANVAS_H}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              style={{
                width: "100%", maxWidth: CANVAS_W, display: "block",
                borderRadius: 8, border: `1px solid ${C.cardBorder}`,
              }}
            />
            
            {snapshotError && streamMode === "snapshot" && <SnapshotError message={snapshotError} />}
            {streamError && streamMode === "live" && <SnapshotError message={streamError} />}
          </div>

          {/* Controls row */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {/* Coordinates */}
            <div style={{
              background: C.card, borderRadius: 8, padding: 16,
              border: `1px solid ${C.cardBorder}`, flex: "1 1 300px",
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                📐 ROI Coordinates <span style={{ fontWeight: 400 }}>(0.0 – 1.0)</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {[
                  ["x1", "X1 (left)", roi.x1],
                  ["y1", "Y1 (top)", roi.y1],
                  ["x2", "X2 (right)", roi.x2],
                  ["y2", "Y2 (bottom)", roi.y2],
                ].map(([key, label, val]) => (
                  <div key={key}>
                    <div style={{ fontSize: 10, color: C.dim, marginBottom: 4 }}>{label}</div>
                    <input
                      type="number" min={0} max={1} step={0.005}
                      value={parseFloat(val).toFixed(3)}
                      onChange={e => {
                        const v = Math.max(0, Math.min(1, parseFloat(e.target.value) || 0));
                        setRoi(prev => ({ ...prev, [key]: v }));
                      }}
                      style={{
                        width: "100%", padding: "6px 10px", borderRadius: 4,
                        border: `1px solid ${C.cardBorder}`,
                        background: C.bg, color: C.blueBright,
                        fontSize: 13, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600,
                        outline: "none",
                      }}
                    />
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 10, fontSize: 10, color: C.dim }}>
                Area: {((roi.x2 - roi.x1) * 100).toFixed(0)}% × {((roi.y2 - roi.y1) * 100).toFixed(0)}%
                = {((roi.x2 - roi.x1) * (roi.y2 - roi.y1) * 100).toFixed(1)}% of frame
              </div>
            </div>

            {/* Save */}
            <div style={{
              background: C.card, borderRadius: 8, padding: 16,
              border: `1px solid ${hasChanges ? C.amber : C.cardBorder}`,
              flex: "1 1 300px", display: "flex", flexDirection: "column", justifyContent: "space-between",
            }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  💾 Apply to System
                </div>
                <div style={{ fontSize: 12, color: C.text, lineHeight: 1.7, marginBottom: 12 }}>
                  กด <strong>Apply ROI</strong> เพื่อบันทึกค่าลง Redis
                  <br />→ rtsp-producer จะใช้ค่าใหม่ทันที (ไม่ต้อง restart)
                </div>
                {hasChanges && (
                  <div style={{
                    padding: "6px 10px", borderRadius: 4,
                    background: C.amberDim, border: `1px solid rgba(245,158,11,0.2)`,
                    fontSize: 11, color: C.amber, marginBottom: 10,
                  }}>
                    ⚠ มีค่าที่ยังไม่ได้บันทึก
                  </div>
                )}
                {saveResult && (
                  <div style={{
                    padding: "6px 10px", borderRadius: 4, fontSize: 11, marginBottom: 10,
                    background: saveResult.ok ? C.greenDim : C.redDim,
                    border: `1px solid ${saveResult.ok ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}`,
                    color: saveResult.ok ? C.green : C.red,
                  }}>
                    {saveResult.ok ? "✓ " : "✗ "}{saveResult.message}
                  </div>
                )}
              </div>
              <button onClick={handleSave} disabled={saving || !hasChanges} style={{
                padding: "10px 0", borderRadius: 6, border: "none",
                fontSize: 13, fontWeight: 700,
                cursor: saving || !hasChanges ? "not-allowed" : "pointer",
                background: hasChanges ? C.blue : C.cardBorder,
                color: hasChanges ? "#fff" : C.dim,
                opacity: saving ? 0.6 : 1, transition: "all 0.2s",
              }}>
                {saving ? "⏳ Saving..." : hasChanges ? "✓ Apply ROI" : "No Changes"}
              </button>
            </div>
          </div>

          {/* Track IDs + trigger captures */}
          <div style={{
            marginTop: 16,
            background: C.card, borderRadius: 8, padding: 14,
            border: `1px solid ${C.cardBorder}`
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              🚗 Tracking IDs + Trigger Captures
            </div>
            <div style={{ fontSize: 11, color: C.dim, marginBottom: 10 }}>
              ใช้ Track ID จาก object tracking โดยตรง และ Capture 1 ครั้ง/ID เมื่อรถวิ่งข้ามเส้น Trigger
            </div>

            <div style={{ display: "grid", gap: 8, maxHeight: 180, overflowY: "auto", marginBottom: 12 }}>
              {trackedObjects.length === 0 && <div style={{ color: C.dim, fontSize: 11 }}>ยังไม่พบ tracking object</div>}
              {trackedObjects.map(obj => (
                <div key={`track-${obj.track_id}`} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  border: `1px solid ${C.cardBorder}`, borderRadius: 6, padding: "6px 8px",
                  background: "rgba(245,158,11,0.06)"
                }}>
                  <div style={{ fontSize: 11, color: C.text }}>
                    <strong style={{ color: "#fbbf24" }}>Track ID {obj.track_id}</strong>
                  </div>
                  <div style={{ fontSize: 10, color: C.dim }}>
                    {capturedTracks[String(obj.track_id)] ? "captured" : "waiting"}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
              {Object.values(capturedTracks).length === 0 && (
                <div style={{ color: C.dim, fontSize: 11 }}>ยังไม่มี snapshot จาก trigger line</div>
              )}
              {Object.values(capturedTracks).sort((a, b) => (b.ts_ms || 0) - (a.ts_ms || 0)).map(track => (
                <div key={`capture-${track.track_id}`} style={{
                  border: `1px solid ${C.cardBorder}`, borderRadius: 6, overflow: "hidden", background: C.bg
                }}>
                  {track.image ? (
                    <img src={track.image} alt={`track-${track.track_id}`} style={{ width: "100%", height: 72, objectFit: "cover", display: "block" }} />
                  ) : (
                    <div style={{ height: 72, display: "grid", placeItems: "center", color: C.dim, fontSize: 10 }}>no image</div>
                  )}
                  <div style={{ padding: 6, fontSize: 10, color: C.text, fontFamily: "monospace" }}>
                    TID {track.track_id}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Tips */}
          <div style={{ marginTop: 18, padding: 14, borderRadius: 8, background: C.card, border: `1px solid ${C.cardBorder}` }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.dim, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              💡 Tips
            </div>
            <div style={{ fontSize: 11, color: C.dim, lineHeight: 1.9 }}>
              • <strong style={{ color: C.text }}>Live Stream:</strong> แสดงวิดีโอแบบเรียลไทม์ (ต้องเปิด RTSP producer)
              <br />
              • <strong style={{ color: C.text }}>Snapshot:</strong> แคปภาพเฟรมเดียว พร้อม auto-refresh
              <br />
              • ลาก <strong style={{ color: C.text }}>มุม</strong> เพื่อย่อ/ขยาย &nbsp;|&nbsp;
              ลาก <strong style={{ color: C.text }}>ขอบ</strong> เพื่อปรับด้านเดียว &nbsp;|&nbsp;
              ลาก <strong style={{ color: C.text }}>ตรงกลาง</strong> เพื่อเลื่อน ROI ทั้งกรอบ
              <br />
              • ROI ที่ดี: ครอบคลุมตำแหน่งที่เห็นป้ายทะเบียน<strong style={{ color: C.text }}>ชัดที่สุด</strong>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}