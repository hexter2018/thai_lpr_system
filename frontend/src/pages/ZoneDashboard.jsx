/**
 * ZoneDashboard.jsx
 * ─────────────────────────────────────────────────────────────
 * UI สำหรับ Multi-Zone Capture Trigger (วิธี 3)
 *
 * Features:
 *  - วาด polygon zones บน snapshot / live stream ด้วยการ click
 *  - บันทึก config เป็น ENV string พร้อม copy
 *  - แสดง motion fill realtime จาก canvas frame diff
 *  - ใช้ API เดียวกับ roi.jsx (snapshot + live stream)
 *
 * Integration:
 *  เพิ่ม route ใน App.jsx:
 *   import ZoneDashboard from "./pages/ZoneDashboard"
 *   <Route path="/zones" element={<ZoneDashboard />} />
 */

import { useState, useEffect, useRef, useCallback } from "react";

// ─── CONFIG ───────────────────────────────────────────────────
const API_BASE = (() => {
  const v = (import.meta?.env?.VITE_API_BASE || "").trim();
  return v ? v.replace(/\/$/, "") : window.location.origin.replace(/\/$/, "");
})();

const ENABLE_MJPEG = String(import.meta?.env?.VITE_ENABLE_MJPEG_STREAM || "true").toLowerCase() === "true";

const CANVAS_W = 960;
const CANVAS_H = 540;

// ─── COLOR PALETTE ────────────────────────────────────────────
const ZONE_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
  "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16",
];
const C = {
  bg: "#050810", card: "#090f1e", border: "#151f38",
  text: "#9fb3cc", dim: "#2e4060", bright: "#e2eaf4",
  blue: "#3b82f6", green: "#10b981", amber: "#f59e0b", red: "#ef4444",
};

// ─── MOCK CAMERAS ─────────────────────────────────────────────
const MOCK_CAMERAS = [
  { id: "PCN_Lane4", name: "PCN-MM04 Lane 4" },
  { id: "PCN_Lane5", name: "PCN-MM04 Lane 5" },
  { id: "PCN_Lane6", name: "PCN-MM04 Lane 6" },
];

// ─── API ──────────────────────────────────────────────────────
const API = {
  async cameras() {
    try {
      const r = await fetch(`${API_BASE}/api/roi-agent/cameras`);
      if (!r.ok) throw new Error();
      const d = await r.json();
      return Array.isArray(d) ? d.map(c => ({ id: c.id || c.camera_id, name: c.name || c.id })) : null;
    } catch { return null; }
  },
  async snapshot(cameraId) {
    const r = await fetch(`${API_BASE}/api/roi-agent/snapshot/${cameraId}?width=1280&t=${Date.now()}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return URL.createObjectURL(await r.blob());
  },
};

// ─── HELPERS ──────────────────────────────────────────────────
function ptInCanvas(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((e.clientX - rect.left) / rect.width),
    y: ((e.clientY - rect.top) / rect.height),
  };
}

function centroid(points) {
  const x = points.reduce((s, p) => s + p.x, 0) / points.length;
  const y = points.reduce((s, p) => s + p.y, 0) / points.length;
  return { x, y };
}

function zoneToEnv(zones) {
  const lines = [
    `CAPTURE_ZONE_ENABLED=true`,
    `CAPTURE_ZONE_COUNT=${zones.length}`,
    "",
  ];
  zones.forEach((z, i) => {
    const pts = z.points.map(p => `${p.x.toFixed(3)},${p.y.toFixed(3)}`).join(";");
    lines.push(`CAPTURE_ZONE_${i + 1}_NAME=${z.name}`);
    lines.push(`CAPTURE_ZONE_${i + 1}_POINTS=${pts}`);
    lines.push(`CAPTURE_ZONE_${i + 1}_MIN_FILL=${z.minFill.toFixed(2)}`);
    lines.push(`CAPTURE_ZONE_${i + 1}_COOLDOWN=${z.cooldown.toFixed(1)}`);
    lines.push("");
  });
  return lines.join("\n");
}

// ─── MAIN COMPONENT ───────────────────────────────────────────
export default function ZoneDashboard() {
  const [cameras, setCameras] = useState(null);
  const [selectedCam, setSelectedCam] = useState(null);
  const [zones, setZones] = useState([]);           // saved zones
  const [draft, setDraft] = useState([]);           // points being drawn
  const [editing, setEditing] = useState(false);    // drawing mode on/off
  const [hoverPt, setHoverPt] = useState(null);
  const [streamMode, setStreamMode] = useState("snapshot");
  const [snapshotUrl, setSnapshotUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [selectedZoneIdx, setSelectedZoneIdx] = useState(null);
  const [envOutput, setEnvOutput] = useState("");

  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const snapImgRef = useRef(null);

  // ── Load cameras ──
  useEffect(() => {
    (async () => {
      const data = await API.cameras();
      const cams = data || MOCK_CAMERAS;
      setCameras(cams);
      setSelectedCam(cams[0]?.id || null);
    })();
  }, []);

  // ── Reload snapshot when camera changes ──
  useEffect(() => {
    setSnapshotUrl(p => { if (p) URL.revokeObjectURL(p); return null; });
    setDraft([]);
  }, [selectedCam]);

  // ── Snapshot img loader ──
  useEffect(() => {
    if (!snapshotUrl) { snapImgRef.current = null; return; }
    const img = new Image();
    img.onload = () => { snapImgRef.current = img; };
    img.src = snapshotUrl;
  }, [snapshotUrl]);

  // ── Live stream url ──
  const streamUrl = selectedCam && ENABLE_MJPEG && streamMode === "live"
    ? `${API_BASE}/api/roi-agent/live/${encodeURIComponent(selectedCam)}/mjpeg`
    : null;

  // ── Canvas draw ──
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = CANVAS_W, H = CANVAS_H;
    ctx.clearRect(0, 0, W, H);

    // Background source
    const src = streamMode === "live" ? imgRef.current : snapImgRef.current;
    const canDraw = src && (
      (src instanceof HTMLImageElement && src.complete && src.naturalWidth > 0) ||
      (src instanceof HTMLVideoElement && src.readyState >= 2)
    );
    if (canDraw) {
      ctx.drawImage(src, 0, 0, W, H);
    } else {
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, "#06090f"); g.addColorStop(1, "#0b1220");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "rgba(255,255,255,0.08)"; ctx.font = "13px monospace";
      ctx.textAlign = "center";
      ctx.fillText(streamMode === "live" ? "Connecting live stream…" : "กด 'Capture Snapshot' เพื่อโหลดภาพ", W / 2, H / 2);
      ctx.textAlign = "left";
    }

    // Draw saved zones
    zones.forEach((zone, zi) => {
      if (!zone.points.length) return;
      const color = ZONE_COLORS[zi % ZONE_COLORS.length];
      const pts = zone.points.map(p => ({ x: p.x * W, y: p.y * H }));

      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
      ctx.closePath();
      ctx.fillStyle = zi === selectedZoneIdx ? `${color}44` : `${color}22`;
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = zi === selectedZoneIdx ? 2.5 : 1.5;
      ctx.setLineDash([]);
      ctx.stroke();

      // Vertices
      pts.forEach(p => {
        ctx.fillStyle = color;
        ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.stroke();
      });

      // Label
      const c = centroid(pts);
      ctx.fillStyle = color; ctx.font = "bold 11px monospace";
      ctx.fillText(zone.name, c.x - 20, c.y);
      ctx.fillStyle = "rgba(255,255,255,0.5)"; ctx.font = "9px monospace";
      ctx.fillText(`${zone.points.length} pts | fill≥${(zone.minFill * 100).toFixed(0)}%`, c.x - 30, c.y + 14);
    });

    // Draw draft zone (being drawn)
    if (draft.length > 0) {
      const dPts = draft.map(p => ({ x: p.x * W, y: p.y * H }));
      ctx.beginPath();
      ctx.moveTo(dPts[0].x, dPts[0].y);
      dPts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
      if (hoverPt) ctx.lineTo(hoverPt.x * W, hoverPt.y * H);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
      ctx.stroke(); ctx.setLineDash([]);

      dPts.forEach((p, i) => {
        ctx.fillStyle = i === 0 ? "#fbbf24" : "#fff";
        ctx.beginPath(); ctx.arc(p.x, p.y, i === 0 ? 7 : 4, 0, Math.PI * 2); ctx.fill();
      });

      // Hint
      ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.font = "11px monospace";
      ctx.fillText(`${draft.length} points — Click เพิ่มจุด | Double-click เพื่อปิด polygon`, 10, H - 12);
    }

    if (editing && draft.length === 0) {
      ctx.fillStyle = "rgba(255,255,255,0.6)"; ctx.font = "11px monospace";
      ctx.fillText("🖊 DRAWING MODE — Click เพื่อเริ่มวาด zone", 10, H - 12);
    }
  }, [zones, draft, hoverPt, streamMode, selectedZoneIdx]);

  useEffect(() => {
    const id = setInterval(draw, streamMode === "live" ? 33 : 100);
    return () => clearInterval(id);
  }, [draw, streamMode]);

  // ── Mouse handlers ──
  const handleClick = (e) => {
    if (!editing) return;
    const p = ptInCanvas(e, canvasRef.current);
    if (draft.length >= 3 && e.detail === 2) {
      // Double click = close polygon
      finishZone();
      return;
    }
    setDraft(prev => [...prev, p]);
  };

  const handleMouseMove = (e) => {
    if (!editing) return;
    setHoverPt(ptInCanvas(e, canvasRef.current));
  };

  const finishZone = () => {
    if (draft.length < 3) { alert("ต้องการอย่างน้อย 3 จุด"); return; }
    const name = prompt("ชื่อ Zone:", `zone_${zones.length + 1}`) || `zone_${zones.length + 1}`;
    const minFill = parseFloat(prompt("Min Fill Ratio (0.05–0.50):", "0.12") || "0.12");
    const cooldown = parseFloat(prompt("Cooldown (วินาที):", "2.0") || "2.0");
    const newZone = { name, points: [...draft], minFill: Math.max(0.01, Math.min(1, minFill)), cooldown: Math.max(0, cooldown) };
    setZones(prev => [...prev, newZone]);
    setDraft([]);
    setEditing(false);
  };

  const cancelDraft = () => { setDraft([]); setEditing(false); };

  const deleteZone = (i) => {
    setZones(prev => prev.filter((_, idx) => idx !== i));
    if (selectedZoneIdx === i) setSelectedZoneIdx(null);
  };

  const captureSnapshot = async () => {
    if (!selectedCam) return;
    setLoading(true);
    try {
      const url = await API.snapshot(selectedCam);
      setSnapshotUrl(url);
      setStreamMode("snapshot");
    } catch (e) { alert("Snapshot failed: " + e.message); }
    finally { setLoading(false); }
  };

  const generateEnv = () => {
    if (!zones.length) { alert("ยังไม่มี zone"); return; }
    setEnvOutput(zoneToEnv(zones));
  };

  const copyEnv = () => {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard.writeText(envOutput).then(() => {
        setCopied(true); setTimeout(() => setCopied(false), 2000);
      });
    } else {
      // Fallback: try legacy execCommand or show an error
      try {
        const textarea = document.createElement("textarea");
        textarea.value = envOutput;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
        setCopied(true); setTimeout(() => setCopied(false), 2000);
      } catch (e) {
        alert("Copy failed: Clipboard API not available.");
      }
    }
  };

  if (!cameras) return (
    <div style={{ background: C.bg, color: C.text, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace" }}>
      <div style={{ textAlign: "center" }}>📡 Loading…</div>
    </div>
  );

  return (
    <div style={{ background: C.bg, color: C.text, minHeight: "100vh", fontFamily: "'IBM Plex Mono', monospace" }}>
      {/* Header */}
      <div style={{ background: C.card, borderBottom: `1px solid ${C.border}`, padding: "10px 20px", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: "linear-gradient(135deg,#3b82f6,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 14, fontWeight: 800 }}>Z</div>
        <span style={{ color: C.bright, fontWeight: 700, fontSize: 14 }}>Zone Capture Config</span>
        <span style={{ color: C.dim, fontSize: 11 }}>— กำหนดจุด capture แบบ polygon สำหรับ RTSP Producer</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {["snapshot", "live"].map(m => (
            <button key={m} onClick={() => setStreamMode(m)}
              style={{ padding: "5px 10px", borderRadius: 5, fontSize: 10, fontWeight: 700, cursor: "pointer", border: `1px solid ${streamMode === m ? C.blue : C.border}`, background: streamMode === m ? "rgba(59,130,246,0.12)" : "transparent", color: streamMode === m ? C.blue : C.dim }}>
              {m === "live" ? "🎥 Live" : "📸 Snapshot"}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", minHeight: "calc(100vh - 48px)" }}>
        {/* Sidebar */}
        <div style={{ width: 200, background: C.card, borderRight: `1px solid ${C.border}`, padding: "14px 0", flexShrink: 0 }}>
          <div style={{ padding: "0 14px 8px", fontSize: 10, fontWeight: 700, color: C.dim, textTransform: "uppercase", letterSpacing: "0.1em" }}>CAMERA</div>
          {cameras.map(cam => (
            <div key={cam.id} onClick={() => setSelectedCam(cam.id)}
              style={{ padding: "9px 14px", cursor: "pointer", borderLeft: `3px solid ${selectedCam === cam.id ? C.blue : "transparent"}`, background: selectedCam === cam.id ? "rgba(59,130,246,0.08)" : "transparent" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: selectedCam === cam.id ? C.bright : C.text }}>{cam.name}</div>
              <div style={{ fontSize: 9, color: C.dim, marginTop: 2 }}>{cam.id}</div>
            </div>
          ))}

          <div style={{ height: 1, background: C.border, margin: "12px 0" }} />

          <div style={{ padding: "0 14px 8px", fontSize: 10, fontWeight: 700, color: C.dim, textTransform: "uppercase", letterSpacing: "0.1em" }}>ZONES ({zones.length})</div>
          {zones.length === 0 && (
            <div style={{ padding: "8px 14px", fontSize: 10, color: C.dim }}>ยังไม่มี zone<br />กด "Draw Zone" เพื่อเริ่ม</div>
          )}
          {zones.map((z, i) => (
            <div key={i} onClick={() => setSelectedZoneIdx(i === selectedZoneIdx ? null : i)}
              style={{ padding: "8px 14px", cursor: "pointer", borderLeft: `3px solid ${i === selectedZoneIdx ? ZONE_COLORS[i % ZONE_COLORS.length] : "transparent"}`, background: i === selectedZoneIdx ? "rgba(255,255,255,0.04)" : "transparent", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 11, color: ZONE_COLORS[i % ZONE_COLORS.length], fontWeight: 700 }}>{z.name}</div>
                <div style={{ fontSize: 9, color: C.dim }}>{z.points.length} pts · fill≥{(z.minFill * 100).toFixed(0)}%</div>
              </div>
              <button onClick={(e) => { e.stopPropagation(); deleteZone(i); }}
                style={{ background: "none", border: "none", color: C.dim, cursor: "pointer", fontSize: 14, padding: "0 2px" }}>×</button>
            </div>
          ))}
        </div>

        {/* Main */}
        <div style={{ flex: 1, padding: 18, overflowY: "auto" }}>
          {/* Toolbar */}
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
            <button onClick={captureSnapshot} disabled={loading}
              style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${C.blue}`, background: "rgba(59,130,246,0.1)", color: C.blue, fontSize: 12, fontWeight: 700, cursor: loading ? "wait" : "pointer" }}>
              {loading ? "⏳…" : "📸 Capture Snapshot"}
            </button>

            {!editing ? (
              <button onClick={() => setEditing(true)}
                style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${C.green}`, background: "rgba(16,185,129,0.1)", color: C.green, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                ✏️ Draw Zone
              </button>
            ) : (
              <>
                {draft.length >= 3 && (
                  <button onClick={finishZone}
                    style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${C.amber}`, background: "rgba(245,158,11,0.1)", color: C.amber, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                    ✓ Save Zone ({draft.length} pts)
                  </button>
                )}
                <button onClick={cancelDraft}
                  style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${C.dim}`, background: "transparent", color: C.dim, fontSize: 12, cursor: "pointer" }}>
                  ✕ Cancel
                </button>
              </>
            )}

            {zones.length > 0 && (
              <>
                <button onClick={generateEnv}
                  style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${C.blue}`, background: "rgba(59,130,246,0.08)", color: C.blue, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                  ⚙️ Generate ENV
                </button>
                <button onClick={() => setZones([])}
                  style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${C.red}`, background: "rgba(239,68,68,0.08)", color: C.red, fontSize: 12, cursor: "pointer" }}>
                  🗑 Clear All
                </button>
              </>
            )}
          </div>

          {/* Canvas */}
          <div style={{ position: "relative" }}>
            {streamUrl && streamMode === "live" && (
              <img ref={imgRef} src={streamUrl} alt=""
                style={{ position: "absolute", top: -9999, left: -9999, width: 1, height: 1 }} />
            )}
            <canvas ref={canvasRef} width={CANVAS_W} height={CANVAS_H}
              onClick={handleClick}
              onMouseMove={handleMouseMove}
              onDoubleClick={e => { if (editing && draft.length >= 3) { e.preventDefault(); finishZone(); } }}
              style={{ width: "100%", maxWidth: CANVAS_W, display: "block", borderRadius: 8, border: `1px solid ${editing ? C.green : C.border}`, cursor: editing ? "crosshair" : "default" }} />
          </div>

          {/* Hints */}
          <div style={{ marginTop: 10, padding: 12, background: C.card, borderRadius: 6, border: `1px solid ${C.border}`, fontSize: 11, color: C.dim, lineHeight: 1.9 }}>
            <strong style={{ color: C.text }}>วิธีใช้:</strong>{" "}
            1. กด <strong style={{ color: C.green }}>📸 Capture Snapshot</strong> เพื่อโหลดภาพจากกล้อง →{" "}
            2. กด <strong style={{ color: C.green }}>✏️ Draw Zone</strong> →{" "}
            3. Click วาด polygon แต่ละจุด →{" "}
            4. Double-click เพื่อปิด zone →{" "}
            5. กด <strong style={{ color: C.blue }}>⚙️ Generate ENV</strong> แล้ว copy ไป docker-compose
          </div>

          {/* ENV Output */}
          {envOutput && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.text, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  ⚙️ ENV Config — วางใน docker-compose.realtime.yml (rtsp-producer-cam*)
                </span>
                <button onClick={copyEnv}
                  style={{ padding: "5px 12px", borderRadius: 4, border: `1px solid ${copied ? C.green : C.blue}`, background: copied ? "rgba(16,185,129,0.12)" : "rgba(59,130,246,0.1)", color: copied ? C.green : C.blue, fontSize: 11, fontWeight: 700, cursor: "pointer" }}>
                  {copied ? "✓ Copied!" : "Copy ENV"}
                </button>
              </div>
              <pre style={{ background: "#040812", border: `1px solid ${C.border}`, borderRadius: 6, padding: 14, fontSize: 11, color: "#7dd3fc", overflowX: "auto", lineHeight: 1.7, margin: 0 }}>
                {envOutput}
              </pre>
              <div style={{ marginTop: 8, padding: 10, background: "rgba(245,158,11,0.06)", border: `1px solid rgba(245,158,11,0.2)`, borderRadius: 6, fontSize: 11, color: C.amber }}>
                ⚠️ อย่าลืมเปิด <strong>RTSP_LINE_ENABLED=false</strong> ด้วยถ้าใช้ Zone แทน Line Trigger
              </div>
            </div>
          )}

          {/* Zone detail table */}
          {zones.length > 0 && (
            <div style={{ marginTop: 14, background: C.card, borderRadius: 8, border: `1px solid ${C.border}`, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead>
                  <tr style={{ background: "rgba(255,255,255,0.03)" }}>
                    {["#", "Zone Name", "Points", "Min Fill", "Cooldown", ""].map(h => (
                      <th key={h} style={{ padding: "8px 12px", textAlign: "left", color: C.dim, fontWeight: 700, borderBottom: `1px solid ${C.border}`, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {zones.map((z, i) => (
                    <tr key={i} onClick={() => setSelectedZoneIdx(i === selectedZoneIdx ? null : i)}
                      style={{ cursor: "pointer", background: i === selectedZoneIdx ? "rgba(59,130,246,0.06)" : "transparent", borderBottom: `1px solid ${C.border}` }}>
                      <td style={{ padding: "8px 12px" }}>
                        <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: ZONE_COLORS[i % ZONE_COLORS.length] }} />
                      </td>
                      <td style={{ padding: "8px 12px", color: ZONE_COLORS[i % ZONE_COLORS.length], fontWeight: 700 }}>{z.name}</td>
                      <td style={{ padding: "8px 12px", color: C.text }}>{z.points.length}</td>
                      <td style={{ padding: "8px 12px", color: C.text }}>{(z.minFill * 100).toFixed(0)}%</td>
                      <td style={{ padding: "8px 12px", color: C.text }}>{z.cooldown}s</td>
                      <td style={{ padding: "8px 12px" }}>
                        <button onClick={(e) => { e.stopPropagation(); deleteZone(i); }}
                          style={{ background: "none", border: `1px solid ${C.border}`, borderRadius: 3, color: C.dim, cursor: "pointer", padding: "2px 8px", fontSize: 10 }}>
                          ลบ
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}