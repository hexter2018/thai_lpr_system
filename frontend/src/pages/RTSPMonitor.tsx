import React, { useEffect, useMemo, useRef, useState } from "react";

type Point = { x: number; y: number }; // normalized 0..1
type LineDir = "A_TO_B" | "B_TO_A";

type VirtualLine = {
  id: string;
  name: string;
  color: string; // hex
  p1: Point;
  p2: Point;
  direction: LineDir;
};

type OverlayPayload = {
  camera_id: string;
  lines: VirtualLine[];
};

type TrackedObject = {
  track_id: number;
  cls?: string;
  bbox: [number, number, number, number]; // normalized [x1,y1,x2,y2]
  speed_kmh?: number;
  plate?: string;
  conf?: number;
};

type WsPayload = {
  ts: number;
  camera_id: string;
  objects: TrackedObject[];
};

const API_BASE = (import.meta as any).env.VITE_API_BASE?.replace(/\/$/, "") || "";
const WS_BASE = (() => {
  // แปลง http(s) -> ws(s)
  if (!API_BASE) return "";
  return API_BASE.startsWith("https")
    ? API_BASE.replace(/^https/, "wss")
    : API_BASE.replace(/^http/, "ws");
})();

function clamp01(v: number) {
  return Math.max(0, Math.min(1, v));
}

function distPx(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function uid(prefix = "line") {
  return `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now()}`;
}

export default function RTSPMonitor() {
  // --- Camera selection ---
  const [cameraId, setCameraId] = useState("PCN_Lane4");

  // --- Stream URL (MJPEG) ---
  const mjpegUrl = useMemo(() => {
    // backend ควรมี: GET /api/streams/{camera_id}/mjpeg
    return `${API_BASE}/api/streams/${encodeURIComponent(cameraId)}/mjpeg`;
  }, [cameraId]);

  // --- Refs for sizing & drawing ---
  const imgRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // --- Overlay state ---
  const [lines, setLines] = useState<VirtualLine[]>([]);
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);

  // draw modes
  const [drawMode, setDrawMode] = useState<"NONE" | "ADD_LINE">("NONE");
  const [tempP1, setTempP1] = useState<Point | null>(null);

  // drag endpoint
  const dragRef = useRef<{ lineId: string; endpoint: "p1" | "p2" } | null>(null);

  // --- Tracking boxes state (from WS) ---
  const [objects, setObjects] = useState<TrackedObject[]>([]);
  const [showBoxes, setShowBoxes] = useState(true);
  const [showIds, setShowIds] = useState(true);
  const [showSpeed, setShowSpeed] = useState(true);

  // --- API calls: load/save overlays ---
  async function loadOverlays(camId: string) {
    // backend ควรมี: GET /api/cameras/{camera_id}/overlays
    const url = `${API_BASE}/api/cameras/${encodeURIComponent(camId)}/overlays`;
    const res = await fetch(url);
    if (res.status === 404) {
      setLines([]); // no overlays yet
      setSelectedLineId(null);
      return;
    }
    if (!res.ok) throw new Error(`Load overlays failed: ${res.status}`);
    const data = (await res.json()) as OverlayPayload;
    setLines(data.lines || []);
    setSelectedLineId(null);
  }

  async function saveOverlays(camId: string, payloadLines: VirtualLine[]) {
    // backend ควรมี: PUT /api/cameras/{camera_id}/overlays
    const url = `${API_BASE}/api/cameras/${encodeURIComponent(camId)}/overlays`;
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ camera_id: camId, lines: payloadLines } satisfies OverlayPayload),
    });
    if (!res.ok) throw new Error(`Save overlays failed: ${res.status}`);
  }

  // load overlays when camera changes
  useEffect(() => {
    loadOverlays(cameraId).catch((e) => {
      console.warn(e);
      setLines([]); // ถ้า backend ยังไม่มี endpoint จะไม่พัง UI
    });
  }, [cameraId]);

  // --- WebSocket for boxes/ids ---
  useEffect(() => {
    if (!WS_BASE) return;

    // backend ควรมี: WS /ws/cameras/{camera_id}
    const wsUrl = `${WS_BASE}/ws/cameras/${encodeURIComponent(cameraId)}`;
    const ws = new WebSocket(wsUrl);
    let isActive = true;

    ws.onopen = () => console.log("WS connected:", wsUrl);
    ws.onclose = (evt) => {
      if (!isActive) return;
      if (evt.code !== 1000) {
        console.warn(`WS closed (${evt.code}) for ${cameraId}`);
      }
    };
    ws.onerror = (evt) => {
      console.warn(`WS error for ${cameraId}`);
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data) as WsPayload;
        if (msg?.camera_id === cameraId && Array.isArray(msg.objects)) {
          setObjects(msg.objects);
        }
      } catch {
        // ignore
      }
    };

    return () => {
      isActive = false;
      ws.close();
    };
  }, [cameraId]);

  // --- Canvas sizing (match image box) ---
  function syncCanvasSize() {
    const img = imgRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;

    const rect = img.getBoundingClientRect();
    // match CSS pixel size
    canvas.width = Math.max(1, Math.floor(rect.width));
    canvas.height = Math.max(1, Math.floor(rect.height));
  }

  useEffect(() => {
    const onResize = () => syncCanvasSize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ensure canvas sized when image loads
  function onImgLoad() {
    syncCanvasSize();
  }

  // --- Coordinate conversion ---
  function clientToNorm(clientX: number, clientY: number): Point | null {
    const img = imgRef.current;
    if (!img) return null;
    const rect = img.getBoundingClientRect();
    const x = (clientX - rect.left) / rect.width;
    const y = (clientY - rect.top) / rect.height;
    return { x: clamp01(x), y: clamp01(y) };
  }

  function normToCanvasPx(p: Point): { x: number; y: number } {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    return { x: p.x * canvas.width, y: p.y * canvas.height };
  }

  // --- Hit test endpoints for dragging ---
  function findEndpointHit(normPt: Point): { lineId: string; endpoint: "p1" | "p2" } | null {
    const canvas = canvasRef.current;
    if (!canvas) return null;

    const ptPx = { x: normPt.x * canvas.width, y: normPt.y * canvas.height };
    const HIT_RADIUS = 12; // px

    for (const ln of lines) {
      const p1 = normToCanvasPx(ln.p1);
      const p2 = normToCanvasPx(ln.p2);
      if (distPx(ptPx, p1) <= HIT_RADIUS) return { lineId: ln.id, endpoint: "p1" };
      if (distPx(ptPx, p2) <= HIT_RADIUS) return { lineId: ln.id, endpoint: "p2" };
    }
    return null;
  }

  // --- Mouse handlers ---
  function onMouseDown(e: React.MouseEvent) {
    const np = clientToNorm(e.clientX, e.clientY);
    if (!np) return;

    // ถ้าไม่ได้อยู่ใน draw mode ให้ลองเลือก/ลาก endpoint
    if (drawMode === "NONE") {
      const hit = findEndpointHit(np);
      if (hit) {
        dragRef.current = hit;
        setSelectedLineId(hit.lineId);
        return;
      }
      return;
    }

    // drawMode === ADD_LINE
    if (!tempP1) {
      setTempP1(np);
    } else {
      // click second point -> create line
      const newLine: VirtualLine = {
        id: uid("line"),
        name: `Line ${lines.length + 1}`,
        color: "#ff0000",
        p1: tempP1,
        p2: np,
        direction: "A_TO_B",
      };
      setLines((prev) => [...prev, newLine]);
      setSelectedLineId(newLine.id);
      setTempP1(null);
      setDrawMode("NONE");
    }
  }

  function onMouseMove(e: React.MouseEvent) {
    const np = clientToNorm(e.clientX, e.clientY);
    if (!np) return;

    // drag endpoint
    if (dragRef.current) {
      const { lineId, endpoint } = dragRef.current;
      setLines((prev) =>
        prev.map((ln) => {
          if (ln.id !== lineId) return ln;
          return { ...ln, [endpoint]: np } as VirtualLine;
        })
      );
      return;
    }
  }

  function onMouseUp() {
    dragRef.current = null;
  }

  // --- Drawing loop ---
  useEffect(() => {
    let raf = 0;

    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) {
        raf = requestAnimationFrame(draw);
        return;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        raf = requestAnimationFrame(draw);
        return;
      }

      // clear
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // ---- Draw lines ----
      for (const ln of lines) {
        const p1 = normToCanvasPx(ln.p1);
        const p2 = normToCanvasPx(ln.p2);

        // line
        ctx.lineWidth = 4;
        ctx.strokeStyle = ln.color;
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();

        // endpoints (handles)
        const isSelected = ln.id === selectedLineId;
        ctx.fillStyle = isSelected ? "#ffffff" : "#dddddd";
        ctx.strokeStyle = "#000000";
        for (const p of [p1, p2]) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }

        // label
        ctx.font = "bold 14px sans-serif";
        ctx.fillStyle = ln.color;
        ctx.fillText(`${ln.name}`, p1.x + 8, p1.y - 8);

        // direction arrow (simple)
        const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
        const dir = ln.direction === "A_TO_B" ? 1 : -1;
        const vx = (p2.x - p1.x);
        const vy = (p2.y - p1.y);
        const len = Math.max(1, Math.sqrt(vx * vx + vy * vy));
        const ux = (vx / len) * dir;
        const uy = (vy / len) * dir;
        const arrow = { x: mid.x + ux * 18, y: mid.y + uy * 18 };
        ctx.beginPath();
        ctx.fillStyle = ln.color;
        ctx.arc(arrow.x, arrow.y, 4, 0, Math.PI * 2);
        ctx.fill();
      }

      // temp line while placing second point
      if (drawMode === "ADD_LINE" && tempP1) {
        // show hint
        const p1 = normToCanvasPx(tempP1);
        ctx.font = "14px sans-serif";
        ctx.fillStyle = "#ffffff";
        ctx.fillText("Click second point to finish line", p1.x + 10, p1.y + 20);
      }

      // ---- Draw boxes ----
      if (showBoxes) {
        for (const obj of objects) {
          const [x1, y1, x2, y2] = obj.bbox;
          const rx1 = x1 * canvas.width;
          const ry1 = y1 * canvas.height;
          const rw = (x2 - x1) * canvas.width;
          const rh = (y2 - y1) * canvas.height;

          ctx.lineWidth = 3;
          ctx.strokeStyle = "#ffa500";
          ctx.strokeRect(rx1, ry1, rw, rh);

          // label text
          const parts: string[] = [];
          if (showIds) parts.push(`ID:${obj.track_id}`);
          if (obj.plate) parts.push(obj.plate);
          if (showSpeed && typeof obj.speed_kmh === "number") parts.push(`${obj.speed_kmh.toFixed(0)} km/h`);

          const label = parts.join("  ");
          if (label) {
            ctx.font = "bold 16px sans-serif";
            ctx.fillStyle = "#ffa500";
            ctx.fillText(label, rx1, Math.max(18, ry1 - 6));
          }
        }
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [lines, selectedLineId, drawMode, tempP1, objects, showBoxes, showIds, showSpeed]);

  // --- Right panel actions ---
  const selectedLine = useMemo(() => lines.find((l) => l.id === selectedLineId) || null, [lines, selectedLineId]);

  function updateSelectedLine(patch: Partial<VirtualLine>) {
    if (!selectedLine) return;
    setLines((prev) => prev.map((l) => (l.id === selectedLine.id ? { ...l, ...patch } : l)));
  }

  function deleteSelected() {
    if (!selectedLine) return;
    setLines((prev) => prev.filter((l) => l.id !== selectedLine.id));
    setSelectedLineId(null);
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 12, padding: 12 }}>
      {/* Left: video + canvas */}
      <div style={{ position: "relative", background: "#111", borderRadius: 12, overflow: "hidden" }}>
        <div style={{ padding: 10, display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ color: "#ddd" }}>Camera:</label>
          <input
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: 8, border: "1px solid #333", background: "#1b1b1b", color: "#fff" }}
          />
          <button
            onClick={() => loadOverlays(cameraId).catch((e) => alert(String(e)))}
            style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #333", background: "#222", color: "#fff" }}
          >
            Load Lines
          </button>
          <button
            onClick={() => saveOverlays(cameraId, lines).then(() => alert("Saved")).catch((e) => alert(String(e)))}
            style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #333", background: "#2a2a2a", color: "#fff" }}
          >
            Save Lines
          </button>
          <button
            onClick={() => {
              setDrawMode("ADD_LINE");
              setTempP1(null);
            }}
            style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #333", background: "#0b3", color: "#fff" }}
          >
            + Add Line
          </button>
          <span style={{ color: "#aaa", marginLeft: "auto", fontSize: 12 }}>
            {drawMode === "ADD_LINE" ? "Draw mode: click 2 points" : "Edit: drag endpoints"}
          </span>
        </div>

        <div style={{ position: "relative" }}>
          <img
            ref={imgRef}
            src={mjpegUrl}
            alt="rtsp"
            onLoad={onImgLoad}
            style={{ width: "100%", display: "block" }}
          />

          <canvas
            ref={canvasRef}
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              cursor: drawMode === "ADD_LINE" ? "crosshair" : "default",
            }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
          />
        </div>
      </div>

      {/* Right: controls */}
      <div style={{ background: "#141414", borderRadius: 12, padding: 12, color: "#eee" }}>
        <h3 style={{ margin: 0, marginBottom: 10 }}>Overlay Controls</h3>

        <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
            Boxes
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={showIds} onChange={(e) => setShowIds(e.target.checked)} />
            IDs
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={showSpeed} onChange={(e) => setShowSpeed(e.target.checked)} />
            Speed
          </label>
        </div>

        <hr style={{ borderColor: "#2a2a2a" }} />

        <h4 style={{ marginTop: 10, marginBottom: 8 }}>Lines</h4>
        <div style={{ display: "grid", gap: 8 }}>
          {lines.map((l) => (
            <button
              key={l.id}
              onClick={() => setSelectedLineId(l.id)}
              style={{
                textAlign: "left",
                padding: 10,
                borderRadius: 10,
                border: "1px solid #333",
                background: l.id === selectedLineId ? "#1f1f1f" : "#101010",
                color: "#fff",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                <span style={{ fontWeight: 700 }}>{l.name}</span>
                <span style={{ color: l.color }}>{l.color}</span>
              </div>
              <div style={{ fontSize: 12, color: "#aaa", marginTop: 4 }}>
                dir: {l.direction} | p1({l.p1.x.toFixed(2)},{l.p1.y.toFixed(2)}) → p2({l.p2.x.toFixed(2)},{l.p2.y.toFixed(2)})
              </div>
            </button>
          ))}
          {lines.length === 0 && <div style={{ color: "#aaa" }}>No lines. Click “Add Line”.</div>}
        </div>

        {selectedLine && (
          <>
            <hr style={{ borderColor: "#2a2a2a", marginTop: 12 }} />
            <h4 style={{ marginTop: 10, marginBottom: 8 }}>Selected Line</h4>

            <div style={{ display: "grid", gap: 10 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ color: "#aaa", fontSize: 12 }}>Name</span>
                <input
                  value={selectedLine.name}
                  onChange={(e) => updateSelectedLine({ name: e.target.value })}
                  style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid #333", background: "#0e0e0e", color: "#fff" }}
                />
              </label>

              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ color: "#aaa", fontSize: 12 }}>Color</span>
                <input
                  type="color"
                  value={selectedLine.color}
                  onChange={(e) => updateSelectedLine({ color: e.target.value })}
                  style={{ height: 42, width: "100%", borderRadius: 10, border: "1px solid #333", background: "#0e0e0e" }}
                />
              </label>

              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ color: "#aaa", fontSize: 12 }}>Direction</span>
                <select
                  value={selectedLine.direction}
                  onChange={(e) => updateSelectedLine({ direction: e.target.value as LineDir })}
                  style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid #333", background: "#0e0e0e", color: "#fff" }}
                >
                  <option value="A_TO_B">A_TO_B</option>
                  <option value="B_TO_A">B_TO_A</option>
                </select>
              </label>

              <button
                onClick={deleteSelected}
                style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid #522", background: "#2a1111", color: "#fff" }}
              >
                Delete Line
              </button>
            </div>
          </>
        )}

        <hr style={{ borderColor: "#2a2a2a", marginTop: 12 }} />

        <div style={{ color: "#aaa", fontSize: 12, lineHeight: 1.5 }}>
          <div><b>Tips</b></div>
          <div>• Add Line: click 2 points to create.</div>
          <div>• Edit: drag endpoints (white dots) to adjust.</div>
          <div>• Save Lines: store in backend per camera.</div>
        </div>
      </div>
    </div>
  );
}
