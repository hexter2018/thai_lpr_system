import { useState, useEffect, useCallback, useRef } from "react";

// ─── CONFIG ──────────────────────────────────────────────────
// เปลี่ยน API_BASE เป็น URL ของ FastAPI server จริง
const API_BASE = window.location.origin.includes("localhost")
  ? "http://localhost:8000"
  : window.location.origin;

// ─── API FUNCTIONS ───────────────────────────────────────────
async function fetchCameras() {
  try {
    const res = await fetch(`${API_BASE}/api/roi-agent/cameras`);
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("fetchCameras failed:", e);
    return null;
  }
}

async function fetchSnapshot(cameraId) {
  try {
    const res = await fetch(`${API_BASE}/api/roi-agent/snapshot/${cameraId}?width=1280&t=${Date.now()}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  } catch (e) {
    console.warn("fetchSnapshot failed:", e);
    return null;
  }
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

async function saveRoi(cameraId, roi) {
  try {
    const res = await fetch(`${API_BASE}/api/roi-agent/config/${cameraId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(roi),
    });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `${res.status}`); }
    return await res.json();
  } catch (e) {
    console.warn("saveRoi failed:", e);
    return { ok: false, message: e.message };
  }
}

// ─── COLORS ──────────────────────────────────────────────────
const C = {
  bg: "#060a10", card: "#0c1220", cardHover: "#111a2d",
  border: "#1a2540", borderActive: "#2563eb",
  text: "#c8d6e5", dim: "#4a5c7a", bright: "#f1f5f9",
  blue: "#2563eb", blueGlow: "rgba(37,99,235,0.12)",
  green: "#10b981", greenGlow: "rgba(16,185,129,0.12)",
  red: "#ef4444", redGlow: "rgba(239,68,68,0.12)",
  amber: "#f59e0b",
};

// ─── MOCK DATA (ใช้ตอนไม่มี API) ────────────────────────────
const MOCK_CAMERAS = [
  { id: "cam1", name: "PCN-MM04 Lane 1", rtsp: "rtsp://192.168.1.100:554/stream1", status: "online", roi: { x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 } },
  { id: "cam2", name: "PCN-MM04 Lane 2", rtsp: "rtsp://192.168.1.101:554/stream1", status: "online", roi: { x1: 0.10, y1: 0.25, x2: 0.90, y2: 0.85 } },
  { id: "cam3", name: "PCN-MM04 Lane 3", rtsp: "rtsp://192.168.1.102:554/stream1", status: "offline", roi: null },
];

// ─── MAIN COMPONENT ──────────────────────────────────────────
export default function ROIDashboard() {
  const [cameras, setCameras] = useState(null);
  const [selectedCam, setSelectedCam] = useState(null);
  const [snapshotUrl, setSnapshotUrl] = useState(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [roi, setRoi] = useState({ x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 });
  const [savedRoi, setSavedRoi] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [useMock, setUseMock] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState(null);

  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const [dragging, setDragging] = useState(null);
  const [canvasSize, setCanvasSize] = useState({ w: 960, h: 540 });

  // ── Load cameras on mount ──
  useEffect(() => {
    (async () => {
      const data = await fetchCameras();
      if (data && data.length > 0) {
        setCameras(data);
        setSelectedCam(data[0].id);
        if (data[0].roi) setRoi(data[0].roi);
      } else {
        setUseMock(true);
        setCameras(MOCK_CAMERAS);
        setSelectedCam(MOCK_CAMERAS[0].id);
        if (MOCK_CAMERAS[0].roi) setRoi(MOCK_CAMERAS[0].roi);
      }
    })();
  }, []);

  // ── Load ROI when camera changes ──
  useEffect(() => {
    if (!selectedCam) return;
    (async () => {
      const data = await fetchRoi(selectedCam);
      if (data) {
        setRoi(data);
        setSavedRoi(data);
      }
    })();
    setSaveResult(null);
  }, [selectedCam]);

  // ── Capture snapshot ──
  const captureSnapshot = useCallback(async () => {
    if (!selectedCam) return;
    setSnapshotLoading(true);
    const url = await fetchSnapshot(selectedCam);
    if (url) {
      if (snapshotUrl) URL.revokeObjectURL(snapshotUrl);
      setSnapshotUrl(url);
    }
    setSnapshotLoading(false);
  }, [selectedCam, snapshotUrl]);

  // ── Auto-refresh snapshot ──
  useEffect(() => {
    if (refreshInterval) {
      const timer = setInterval(captureSnapshot, refreshInterval * 1000);
      return () => clearInterval(timer);
    }
  }, [refreshInterval, captureSnapshot]);

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
    Math.abs(roi.x1 - savedRoi.x1) > 0.001 || Math.abs(roi.y1 - savedRoi.y1) > 0.001 ||
    Math.abs(roi.x2 - savedRoi.x2) > 0.001 || Math.abs(roi.y2 - savedRoi.y2) > 0.001
  );

  // ── Canvas drawing ──
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Draw snapshot image or placeholder
    if (imgRef.current && imgRef.current.complete && imgRef.current.naturalWidth > 0) {
      ctx.drawImage(imgRef.current, 0, 0, W, H);
    } else {
      // Placeholder — simulated camera view
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, "#0d1117"); grad.addColorStop(0.5, "#151d2b"); grad.addColorStop(1, "#0a0e17");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, W, H);
      // Road markings
      ctx.strokeStyle = "#1a2540";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([10, 15]);
      for (let i = 1; i <= 3; i++) {
        ctx.beginPath();
        ctx.moveTo(W * i / 4, H * 0.2);
        ctx.lineTo(W * i / 4 + (i - 2) * 60, H);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      // Lane dividers
      ctx.strokeStyle = "#2a3550";
      ctx.lineWidth = 2;
      ctx.setLineDash([20, 30]);
      ctx.beginPath(); ctx.moveTo(W * 0.5, H * 0.15); ctx.lineTo(W * 0.5, H); ctx.stroke();
      ctx.setLineDash([]);
      // Simulated vehicle silhouettes
      [[0.32, 0.48, 0.12, 0.18], [0.58, 0.55, 0.11, 0.16], [0.22, 0.68, 0.10, 0.14]].forEach(([cx, cy, rw, rh]) => {
        ctx.fillStyle = "rgba(30,50,80,0.6)";
        ctx.fillRect((cx - rw / 2) * W, (cy - rh / 2) * H, rw * W, rh * H);
        ctx.strokeStyle = "rgba(16,185,129,0.25)";
        ctx.lineWidth = 1;
        ctx.strokeRect((cx - rw / 2) * W, (cy - rh / 2) * H, rw * W, rh * H);
        // Plate position hint
        ctx.strokeStyle = "rgba(37,99,235,0.35)";
        ctx.strokeRect((cx - rw * 0.3) * W, (cy + rh * 0.15) * H, rw * 0.6 * W, rh * 0.2 * H);
      });
      // "No Live Feed" text
      ctx.font = "bold 14px monospace";
      ctx.fillStyle = "rgba(255,255,255,0.15)";
      ctx.textAlign = "center";
      ctx.fillText(useMock ? "⚠ DEMO MODE — กด Capture Snapshot เพื่อดึงภาพจริง" : "กด Capture Snapshot", W / 2, H - 20);
      ctx.textAlign = "left";
    }

    // Dim area OUTSIDE ROI
    const rx1 = roi.x1 * W, ry1 = roi.y1 * H, rx2 = roi.x2 * W, ry2 = roi.y2 * H;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(0, 0, W, ry1);
    ctx.fillRect(0, ry2, W, H - ry2);
    ctx.fillRect(0, ry1, rx1, ry2 - ry1);
    ctx.fillRect(rx2, ry1, W - rx2, ry2 - ry1);

    // ROI border
    ctx.strokeStyle = C.blue;
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.strokeRect(rx1, ry1, rx2 - rx1, ry2 - ry1);
    ctx.setLineDash([]);

    // Fill ROI area with slight tint
    ctx.fillStyle = "rgba(37,99,235,0.04)";
    ctx.fillRect(rx1, ry1, rx2 - rx1, ry2 - ry1);

    // Corner handles
    const handleSize = 8;
    [
      [rx1, ry1], [rx2, ry1], [rx1, ry2], [rx2, ry2],
    ].forEach(([x, y]) => {
      // Outer glow
      ctx.fillStyle = "rgba(37,99,235,0.3)";
      ctx.beginPath(); ctx.arc(x, y, handleSize + 3, 0, Math.PI * 2); ctx.fill();
      // Blue circle
      ctx.fillStyle = C.blue;
      ctx.beginPath(); ctx.arc(x, y, handleSize, 0, Math.PI * 2); ctx.fill();
      // White inner
      ctx.fillStyle = "#fff";
      ctx.beginPath(); ctx.arc(x, y, handleSize - 3, 0, Math.PI * 2); ctx.fill();
    });

    // Edge midpoint handles
    ctx.fillStyle = C.blue;
    [[rx1 + (rx2 - rx1) / 2, ry1], [rx1 + (rx2 - rx1) / 2, ry2],
     [rx1, ry1 + (ry2 - ry1) / 2], [rx2, ry1 + (ry2 - ry1) / 2]].forEach(([x, y]) => {
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
    });

    // ROI label
    ctx.font = "bold 11px monospace";
    ctx.fillStyle = C.blue;
    ctx.fillText("ROI DETECTION ZONE", rx1 + 10, ry1 + 18);
    ctx.font = "10px monospace";
    ctx.fillStyle = "rgba(37,99,235,0.6)";
    ctx.fillText(`(${roi.x1.toFixed(2)}, ${roi.y1.toFixed(2)}) → (${roi.x2.toFixed(2)}, ${roi.y2.toFixed(2)})`, rx1 + 10, ry1 + 32);
    const areaW = ((roi.x2 - roi.x1) * 100).toFixed(0);
    const areaH = ((roi.y2 - roi.y1) * 100).toFixed(0);
    ctx.fillText(`${areaW}% × ${areaH}% of frame`, rx1 + 10, ry1 + 44);

    // Camera info overlay
    const cam = cameras?.find(c => c.id === selectedCam);
    ctx.font = "bold 10px monospace";
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.fillText(`● ${cam?.name || selectedCam}`, 10, 18);
    ctx.fillText(new Date().toLocaleTimeString(), W - 75, 18);

    if (hasChanges) {
      ctx.fillStyle = "rgba(245,158,11,0.8)";
      ctx.font = "bold 11px monospace";
      ctx.fillText("⚠ UNSAVED CHANGES", W - 170, H - 12);
    }
  }, [roi, snapshotUrl, cameras, selectedCam, useMock, hasChanges]);

  useEffect(() => { drawCanvas(); }, [drawCanvas]);

  // ── Load snapshot image ──
  useEffect(() => {
    if (!snapshotUrl) return;
    const img = new Image();
    img.onload = () => { imgRef.current = img; drawCanvas(); };
    img.src = snapshotUrl;
  }, [snapshotUrl, drawCanvas]);

  // ── Mouse interaction ──
  const getHitTarget = (mx, my) => {
    const W = canvasSize.w, H = canvasSize.h;
    const rx1 = roi.x1 * W, ry1 = roi.y1 * H, rx2 = roi.x2 * W, ry2 = roi.y2 * H;
    const threshold = 16;
    const corners = [
      { key: "tl", x: rx1, y: ry1 }, { key: "tr", x: rx2, y: ry1 },
      { key: "bl", x: rx1, y: ry2 }, { key: "br", x: rx2, y: ry2 },
    ];
    for (const c of corners) {
      if (Math.hypot(mx - c.x, my - c.y) < threshold) return c.key;
    }
    // Edge midpoints
    const midT = { key: "t", x: rx1 + (rx2 - rx1) / 2, y: ry1 };
    const midB = { key: "b", x: rx1 + (rx2 - rx1) / 2, y: ry2 };
    const midL = { key: "l", x: rx1, y: ry1 + (ry2 - ry1) / 2 };
    const midR = { key: "r", x: rx2, y: ry1 + (ry2 - ry1) / 2 };
    for (const m of [midT, midB, midL, midR]) {
      if (Math.hypot(mx - m.x, my - m.y) < threshold) return m.key;
    }
    if (mx > rx1 && mx < rx2 && my > ry1 && my < ry2) return "move";
    return null;
  };

  const getCursorForTarget = (target) => {
    const map = { tl: "nw-resize", tr: "ne-resize", bl: "sw-resize", br: "se-resize", t: "n-resize", b: "s-resize", l: "w-resize", r: "e-resize", move: "grab" };
    return map[target] || "crosshair";
  };

  const handleMouseDown = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const scaleX = canvasSize.w / rect.width, scaleY = canvasSize.h / rect.height;
    const mx = (e.clientX - rect.left) * scaleX, my = (e.clientY - rect.top) * scaleY;
    const target = getHitTarget(mx, my);
    if (target) setDragging({ target, startMx: mx, startMy: my, startRoi: { ...roi } });
  };

  const handleMouseMove = (e) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const scaleX = canvasSize.w / rect.width, scaleY = canvasSize.h / rect.height;
    const mx = (e.clientX - rect.left) * scaleX, my = (e.clientY - rect.top) * scaleY;

    if (!dragging) {
      const target = getHitTarget(mx, my);
      if (canvasRef.current) canvasRef.current.style.cursor = getCursorForTarget(target);
      return;
    }

    const W = canvasSize.w, H = canvasSize.h;
    const dx = (mx - dragging.startMx) / W, dy = (my - dragging.startMy) / H;
    const s = dragging.startRoi;
    const cl = (v) => Math.max(0, Math.min(1, v));
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

  const handleMouseUp = () => { setDragging(null); };

  if (!cameras) {
    return (
      <div style={{ background: C.bg, color: C.text, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 24, marginBottom: 8 }}>📡</div>
          <div>Connecting to ALPR system...</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      background: C.bg, color: C.text, minHeight: "100vh",
      fontFamily: "'IBM Plex Sans', 'Noto Sans Thai', system-ui, sans-serif",
    }}>
      {/* ── HEADER ── */}
      <div style={{
        background: C.card, borderBottom: `1px solid ${C.border}`,
        padding: "10px 20px", display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 6,
            background: `linear-gradient(135deg, ${C.blue}, #7c3aed)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, fontWeight: 800, color: "#fff",
          }}>R</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.bright, letterSpacing: "-0.02em" }}>
              ROI Agent <span style={{ color: C.dim, fontWeight: 400, fontSize: 12 }}>— Detection Zone Config</span>
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {useMock && (
            <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: C.redGlow, color: C.amber, fontWeight: 600 }}>
              DEMO MODE
            </span>
          )}
          {!useMock && (
            <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: C.greenGlow, color: C.green, fontWeight: 600 }}>
              ● CONNECTED
            </span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", minHeight: "calc(100vh - 52px)" }}>
        {/* ── SIDEBAR — Camera List ── */}
        <div style={{
          width: 220, background: C.card, borderRight: `1px solid ${C.border}`,
          padding: "16px 0", flexShrink: 0, overflowY: "auto",
        }}>
          <div style={{ padding: "0 16px 12px", fontSize: 10, fontWeight: 700, color: C.dim, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Cameras
          </div>
          {cameras.map(cam => (
            <div key={cam.id} onClick={() => setSelectedCam(cam.id)}
              style={{
                padding: "10px 16px", cursor: "pointer", transition: "all 0.15s",
                background: selectedCam === cam.id ? C.blueGlow : "transparent",
                borderLeft: selectedCam === cam.id ? `3px solid ${C.blue}` : "3px solid transparent",
              }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%",
                  background: cam.status === "online" ? C.green : cam.status === "offline" ? C.red : C.amber,
                  boxShadow: cam.status === "online" ? `0 0 6px ${C.green}` : "none",
                }} />
                <span style={{ fontSize: 12, fontWeight: 600, color: selectedCam === cam.id ? C.bright : C.text }}>
                  {cam.name}
                </span>
              </div>
              <div style={{ fontSize: 9, color: C.dim, marginTop: 4, marginLeft: 15, fontFamily: "monospace" }}>
                {cam.id} • {cam.status}
              </div>
            </div>
          ))}
        </div>

        {/* ── MAIN CONTENT ── */}
        <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
          {/* Snapshot Controls */}
          <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
            <button onClick={captureSnapshot} disabled={snapshotLoading}
              style={{
                padding: "8px 16px", borderRadius: 6, border: `1px solid ${C.borderActive}`,
                background: C.blueGlow, color: C.blue, fontSize: 12, fontWeight: 700,
                cursor: snapshotLoading ? "wait" : "pointer", opacity: snapshotLoading ? 0.6 : 1,
              }}>
              {snapshotLoading ? "⏳ Capturing..." : "📸 Capture Snapshot"}
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 10, color: C.dim }}>Auto-refresh:</span>
              {[null, 5, 10, 30].map(sec => (
                <button key={sec ?? "off"} onClick={() => setRefreshInterval(sec)}
                  style={{
                    padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer",
                    border: `1px solid ${refreshInterval === sec ? C.borderActive : C.border}`,
                    background: refreshInterval === sec ? C.blueGlow : "transparent",
                    color: refreshInterval === sec ? C.blue : C.dim,
                  }}>
                  {sec ? `${sec}s` : "Off"}
                </button>
              ))}
            </div>

            <div style={{ flex: 1 }} />

            {/* Presets */}
            <div style={{ display: "flex", gap: 6 }}>
              <span style={{ fontSize: 10, color: C.dim, alignSelf: "center" }}>Presets:</span>
              {[
                { label: "Toll Booth", roi: { x1: 0.15, y1: 0.30, x2: 0.85, y2: 0.80 } },
                { label: "Wide", roi: { x1: 0.05, y1: 0.15, x2: 0.95, y2: 0.90 } },
                { label: "Center", roi: { x1: 0.25, y1: 0.35, x2: 0.75, y2: 0.75 } },
                { label: "Full", roi: { x1: 0.0, y1: 0.0, x2: 1.0, y2: 1.0 } },
              ].map(p => (
                <button key={p.label} onClick={() => setRoi(p.roi)}
                  style={{
                    padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600,
                    border: `1px solid ${C.border}`, background: C.cardHover, color: C.text, cursor: "pointer",
                  }}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* ── CANVAS ── */}
          <div style={{ position: "relative", marginBottom: 16 }}>
            <canvas
              ref={canvasRef}
              width={canvasSize.w}
              height={canvasSize.h}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              style={{
                width: "100%", maxWidth: canvasSize.w, borderRadius: 8,
                border: `1px solid ${C.border}`,
              }}
            />
          </div>

          {/* ── ROI CONTROLS + SAVE ── */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {/* Coordinate inputs */}
            <div style={{
              background: C.card, borderRadius: 8, padding: 16,
              border: `1px solid ${C.border}`, flex: "1 1 300px",
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.dim, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                📐 ROI Coordinates <span style={{ color: C.dim, fontWeight: 400 }}>(0.0 - 1.0)</span>
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
                      type="number" min={0} max={1} step={0.01} value={val.toFixed(3)}
                      onChange={e => setRoi(prev => ({ ...prev, [key]: Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)) }))}
                      style={{
                        width: "100%", padding: "6px 10px", borderRadius: 4,
                        border: `1px solid ${C.border}`, background: C.bg, color: C.blue,
                        fontSize: 13, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600,
                      }}
                    />
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 12, fontSize: 10, color: C.dim }}>
                Area: {((roi.x2 - roi.x1) * 100).toFixed(0)}% × {((roi.y2 - roi.y1) * 100).toFixed(0)}%
                = {((roi.x2 - roi.x1) * (roi.y2 - roi.y1) * 100).toFixed(1)}% of frame
              </div>
            </div>

            {/* Save panel */}
            <div style={{
              background: C.card, borderRadius: 8, padding: 16,
              border: `1px solid ${hasChanges ? C.amber : C.border}`, flex: "1 1 300px",
              display: "flex", flexDirection: "column", justifyContent: "space-between",
            }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.dim, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  💾 Apply to System
                </div>
                <div style={{ fontSize: 12, color: C.text, lineHeight: 1.6, marginBottom: 12 }}>
                  กด <strong>Apply ROI</strong> เพื่อบันทึกค่าลง Redis
                  <br />→ rtsp-producer จะใช้ค่าใหม่ทันที (ไม่ต้อง restart)
                </div>
                {hasChanges && (
                  <div style={{
                    padding: "6px 10px", borderRadius: 4, background: "rgba(245,158,11,0.08)",
                    border: "1px solid rgba(245,158,11,0.2)", fontSize: 11, color: C.amber, marginBottom: 12,
                  }}>
                    ⚠ มีค่าที่ยังไม่ได้บันทึก
                  </div>
                )}
                {saveResult && (
                  <div style={{
                    padding: "6px 10px", borderRadius: 4, fontSize: 11, marginBottom: 12,
                    background: saveResult.ok ? C.greenGlow : C.redGlow,
                    border: `1px solid ${saveResult.ok ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}`,
                    color: saveResult.ok ? C.green : C.red,
                  }}>
                    {saveResult.ok ? "✓ " : "✗ "}{saveResult.message}
                  </div>
                )}
              </div>
              <button onClick={handleSave} disabled={saving || !hasChanges}
                style={{
                  padding: "10px 0", borderRadius: 6, border: "none", fontSize: 13, fontWeight: 700,
                  cursor: (saving || !hasChanges) ? "not-allowed" : "pointer",
                  background: hasChanges ? C.blue : C.border,
                  color: hasChanges ? "#fff" : C.dim,
                  opacity: saving ? 0.6 : 1, transition: "all 0.2s",
                }}>
                {saving ? "⏳ Saving..." : hasChanges ? "✓ Apply ROI" : "No Changes"}
              </button>
            </div>
          </div>

          {/* ── TIPS ── */}
          <div style={{
            marginTop: 20, padding: 16, borderRadius: 8,
            background: C.card, border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: C.dim, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              💡 Tips
            </div>
            <div style={{ fontSize: 11, color: C.dim, lineHeight: 1.8 }}>
              • ลาก <strong style={{ color: C.text }}>มุม</strong> เพื่อย่อ/ขยาย ROI &nbsp;|&nbsp;
              ลาก <strong style={{ color: C.text }}>ขอบ</strong> เพื่อปรับด้านเดียว &nbsp;|&nbsp;
              ลาก <strong style={{ color: C.text }}>ตรงกลาง</strong> เพื่อเลื่อน ROI ทั้งกรอบ
              <br />
              • ROI ที่ดี: ครอบคลุม <strong style={{ color: C.text }}>ตำแหน่งที่เห็นป้ายทะเบียนชัดที่สุด</strong> — ไม่กว้างเกินไป (เสียเวลา process) ไม่แคบเกินไป (พลาดรถ)
              <br />
              • สำหรับ <strong style={{ color: C.text }}>ด่านเก็บเงิน</strong>: วาง ROI ตรงช่องที่รถจอดพอดี ไม่ต้องรวมพื้นที่เหนือหลังคารถ
              <br />
              • Capture Snapshot บ่อยๆ เพื่อดูว่า ROI ครอบคลุมตำแหน่งรถจริงหรือไม่
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}