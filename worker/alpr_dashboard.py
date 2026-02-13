#!/usr/bin/env python3
"""ALPR monitoring dashboard for YOLO preview/stats."""

import json
import logging
import os
import time
from collections import deque
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string, request
from flask_cors import CORS
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

try:
    from alpr_worker.rtsp.vehicle_detector import VehicleDetector
    from alpr_worker.rtsp.zone_trigger import load_zones_from_env

    ALPR_MODULES_AVAILABLE = True
except ImportError:
    VehicleDetector = None
    load_zones_from_env = None
    ALPR_MODULES_AVAILABLE = False

log = logging.getLogger(__name__)
LOCAL_TZ = timezone(timedelta(hours=7))

app = Flask(__name__)
CORS(app)

redis_client: Optional[Redis] = None
db_session_factory = None
zones_config: List[Any] = []
detector_info: Dict[str, Any] = {}
cameras_config: List[Dict[str, Any]] = []
_stats_history: Dict[str, deque] = {}
_cameras_config_last_refresh: float = 0.0


def _refresh_cameras_config(force: bool = False) -> None:
    global cameras_config, _cameras_config_last_refresh

    now = time.time()
    refresh_interval = max(float(os.getenv("DASHBOARD_CAMERA_REFRESH_SEC", "10")), 1.0)
    if not force and (now - _cameras_config_last_refresh) < refresh_interval:
        return

    refreshed = _load_cameras_from_backend()
    if refreshed:
        cameras_config = refreshed

    _cameras_config_last_refresh = now


def _normalize_camera_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("cameras") or payload.get("data") or []

    if not isinstance(payload, list):
        return []

    cameras: List[Dict[str, Any]] = []
    for camera in payload:
        if not isinstance(camera, dict):
            continue
        camera_id = (
            camera.get("camera_id")
            or camera.get("id")
            or camera.get("cameraId")
            or camera.get("cam_id")
        )
        if not camera_id:
            continue
        cameras.append({
            "id": camera_id,
            "name": camera.get("name") or camera_id,
        })

    return cameras


def _load_cameras_from_backend() -> List[Dict[str, Any]]:
    # FIX: รองรับทั้ง BACKEND_API_URL และ BACKEND_KPI_URL (ใน compose ใช้ชื่อต่างกัน)
    backend_api_url = (
        os.getenv("BACKEND_API_URL")
        or os.getenv("BACKEND_KPI_URL")
        or "http://backend:8000"
    )
    base_url = backend_api_url.rstrip("/")

    # FIX: สลับลำดับ — ใช้ /api/roi-agent/cameras ก่อน เพราะ /api/cameras คืนค่าว่าง []
    endpoints = [
        f"{base_url}/api/roi-agent/cameras",
        f"{base_url}/api/cameras",
    ]

    log.info(f"🔍 Backend URL: {backend_api_url}")

    for index, endpoint in enumerate(endpoints):
        try:
            log.info(f"📡 Trying endpoint {index+1}/{len(endpoints)}: {endpoint}")
            with urlopen(endpoint, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            log.info(f"📥 Response type: {type(payload).__name__}")
            if isinstance(payload, dict):
                log.info(f"📥 Response keys: {list(payload.keys())}")
            elif isinstance(payload, list):
                log.info(f"📥 Response length: {len(payload)}")

        except (URLError, TimeoutError) as exc:
            log.warning(f"⚠️  Connection failed ({endpoint}): {exc}")
            continue
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning(f"⚠️  Invalid JSON ({endpoint}): {exc}")
            continue

        cameras = _normalize_camera_payload(payload)
        if cameras:
            log.info(f"✅ Got {len(cameras)} cameras: {[c['id'] for c in cameras]}")
            return cameras

        log.warning(f"❌ No usable cameras from: {endpoint}")

    log.warning("❌ All backend endpoints failed or returned no cameras")
    return []


def init_globals():
    global redis_client, db_session_factory, zones_config, detector_info, cameras_config

    log.info("=" * 60)
    log.info("🚀 Initializing ALPR Dashboard")
    log.info("=" * 60)

    # Redis connection
    redis_client = None
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        log.info(f"Connecting to Redis: {redis_url}")
        redis_client = Redis.from_url(redis_url)
        redis_client.ping()
        log.info("✅ Redis connected successfully")
    except Exception as exc:
        log.error(f"❌ Redis connection failed: {exc}")

    # Database connection
    try:
        db_url = os.getenv("DATABASE_URL", "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr")
        log.info("Connecting to Database...")
        engine = create_engine(db_url, pool_pre_ping=True)
        db_session_factory = sessionmaker(bind=engine)
        log.info("✅ Database connected successfully")
    except Exception as exc:
        log.error(f"❌ Database connection failed: {exc}")

    # Load zones
    if ALPR_MODULES_AVAILABLE and load_zones_from_env:
        try:
            zones_config = load_zones_from_env()
            log.info(f"✅ Loaded {len(zones_config)} capture zones")
        except Exception as e:
            zones_config = []
            log.warning(f"⚠️  No zones loaded: {e}")

    # Load cameras — ลองจาก backend ก่อน แล้ว fallback ไป env
    log.info("📹 Loading cameras configuration...")
    cameras_config = _load_cameras_from_backend()

    if not cameras_config:
        log.warning("⚠️  No cameras from backend API, trying CAMERAS_CONFIG env...")
        try:
            cameras_json = os.getenv("CAMERAS_CONFIG", "[]")
            log.info(f"CAMERAS_CONFIG raw: {cameras_json[:100]}...")
            cameras_config = json.loads(cameras_json)
            log.info(f"✅ Loaded {len(cameras_config)} cameras from environment")
        except Exception as e:
            log.error(f"❌ Failed to parse CAMERAS_CONFIG: {e}")
            cameras_config = []
    else:
        log.info(f"✅ Loaded {len(cameras_config)} cameras from backend API")

    # FIX: normalize cameras จาก env ให้มี key 'id' เสมอ (กันกรณี format ต่างกัน)
    normalized = []
    for cam in cameras_config:
        if not isinstance(cam, dict):
            continue
        cam_id = (
            cam.get("id")
            or cam.get("camera_id")
            or cam.get("cameraId")
            or cam.get("cam_id")
        )
        if not cam_id:
            continue
        normalized.append({"id": cam_id, "name": cam.get("name") or cam_id})
    cameras_config = normalized

    # Final camera check
    if cameras_config:
        camera_ids = [c["id"] for c in cameras_config]
        log.info(f"📹 Active cameras: {camera_ids}")
    else:
        log.error("❌ NO CAMERAS CONFIGURED! Dashboard will be empty!")
        log.error("   Please check BACKEND_API_URL / BACKEND_KPI_URL or add CAMERAS_CONFIG env")

    # Vehicle detector info
    if ALPR_MODULES_AVAILABLE and VehicleDetector:
        try:
            d = VehicleDetector.__new__(VehicleDetector)
            d.enabled = os.getenv("VEHICLE_DETECTOR_ENABLED", "true").lower() == "true"
            d.model_path = os.getenv("VEHICLE_DETECTOR_MODEL_PATH", "")
            d.conf = float(os.getenv("VEHICLE_DETECTOR_CONF", "0.40"))
            d.iou = float(os.getenv("VEHICLE_DETECTOR_IOU", "0.45"))
            d.imgsz = int(os.getenv("VEHICLE_DETECTOR_IMGSZ", "640"))
            d.device = os.getenv("VEHICLE_DETECTOR_DEVICE", "0")
            d.min_zone_overlap = float(os.getenv("VEHICLE_DETECTOR_MIN_ZONE_OVERLAP", "0.20"))
            d.vehicle_classes = [
                int(c.strip())
                for c in os.getenv("VEHICLE_DETECTOR_CLASSES", "2,3,5,7").split(",")
            ]
            detector_info = d.get_info()
            log.info("✅ Vehicle detector info loaded")
        except Exception as e:
            detector_info = {}
            log.warning(f"⚠️  Vehicle detector info unavailable: {e}")

    log.info("=" * 60)
    log.info(f"Dashboard ready: {len(cameras_config)} cameras, {len(zones_config)} zones")
    log.info("=" * 60)


def _get_frame(camera_id: str) -> Optional[bytes]:
    """Get preview frame from Redis — ลอง 2 key ตามลำดับ"""
    if not redis_client:
        log.debug(f"No Redis client for {camera_id}")
        return None
    try:
        frame = redis_client.get(f"alpr:yolo_preview:{camera_id}")
        if frame:
            log.debug(f"✅ Got frame from alpr:yolo_preview:{camera_id} ({len(frame)} bytes)")
            return frame

        frame = redis_client.get(f"alpr:preview:{camera_id}")
        if frame:
            log.debug(f"✅ Got frame from alpr:preview:{camera_id} ({len(frame)} bytes)")
            return frame

        # ไม่มี frame — log แค่ทุก 60 วินาทีเพื่อไม่ spam log
        if not hasattr(_get_frame, "_last_warn"):
            _get_frame._last_warn = {}

        now = time.time()
        last = _get_frame._last_warn.get(camera_id, 0)
        if now - last > 60:
            _get_frame._last_warn[camera_id] = now
            log.warning(f"❌ No preview frame in Redis for {camera_id}")
            log.warning(f"   Check keys: alpr:yolo_preview:{camera_id} / alpr:preview:{camera_id}")

        return None
    except Exception as e:
        log.error(f"❌ Redis error for {camera_id}: {e}")
        return None


def _placeholder(camera_id: str) -> bytes:
    """สร้าง placeholder frame สีดำพร้อม label ชื่อกล้อง"""
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(img, camera_id, (20, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (120, 120, 120), 2)
    cv2.putText(img, "Waiting for stream...", (20, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes() if ok else b""


def _gen(camera_id: str):
    """Generator สำหรับ MJPEG stream"""
    while True:
        data = _get_frame(camera_id) or _placeholder(camera_id)
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
        time.sleep(0.05)


def _get_camera_stats(camera_id: str) -> Dict[str, Any]:
    if not redis_client:
        return {}
    try:
        raw = redis_client.hgetall(f"rtsp:stats:{camera_id}")
    except Exception:
        return {}
    stats: Dict[str, Any] = {}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        try:
            stats[key] = int(val)
        except ValueError:
            try:
                stats[key] = float(val)
            except ValueError:
                stats[key] = val
    return stats


def _is_alive(camera_id: str) -> bool:
    if not redis_client:
        return False
    try:
        hb = redis_client.get(f"alpr:camera_heartbeat:{camera_id}")
        return hb is not None and (time.time() - float(hb.decode())) < 30
    except Exception:
        return False


def _captures(limit: int = 20) -> List[Dict[str, Any]]:
    if not db_session_factory:
        return []
    db = db_session_factory()
    try:
        rows = db.execute(
            text("""
                SELECT c.id, c.camera_id, c.captured_at, pr.plate_text, pr.confidence, pr.province
                FROM captures c
                LEFT JOIN detections d ON d.capture_id = c.id
                LEFT JOIN plate_reads pr ON pr.detection_id = d.id
                ORDER BY c.captured_at DESC LIMIT :limit
            """),
            {"limit": limit},
        )
        return [
            {
                "id": r.id,
                "camera_id": r.camera_id or "",
                "captured_at": r.captured_at.isoformat() if r.captured_at else "",
                "plate_text": r.plate_text or "",
                "confidence": round(float(r.confidence or 0), 3),
                "province": r.province or "",
            }
            for r in rows
        ]
    finally:
        db.close()


# ==================== Routes ====================

@app.route("/")
def index():
    _refresh_cameras_config()
    return render_template_string(HTML, cameras=cameras_config)


@app.route("/video/<camera_id>")
def video_feed(camera_id):
    return Response(_gen(camera_id), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/stats/<camera_id>")
def api_stats(camera_id):
    stats = _get_camera_stats(camera_id)
    stats["alive"] = _is_alive(camera_id)
    hist = _stats_history.setdefault(camera_id, deque(maxlen=60))
    hist.append({
        "t": int(time.time()),
        "yolo_triggers": stats.get("yolo_zone_triggers", 0),
        "enqueued": stats.get("frames_enqueued", 0),
    })
    stats["history"] = list(hist)[-20:]
    return jsonify(stats)


@app.route("/api/health")
def api_health():
    redis_ok = False
    db_ok = False
    try:
        if redis_client:
            redis_client.ping()
            redis_ok = True
    except Exception:
        pass
    try:
        if db_session_factory:
            db = db_session_factory()
            db.execute(text("SELECT 1"))
            db.close()
            db_ok = True
    except Exception:
        pass
    return jsonify({
        "redis": redis_ok,
        "database": db_ok,
        "zones_count": len(zones_config),
        "cameras_count": len(cameras_config),
    })


@app.route("/api/zones")
def api_zones():
    return jsonify([
        {
            "name": z.name,
            "points": z.points,
            "min_fill_ratio": z.min_fill_ratio,
            "cooldown_sec": z.cooldown_sec,
        }
        for z in zones_config
    ])


@app.route("/api/detector")
def api_detector():
    return jsonify(detector_info)


@app.route("/api/captures")
def api_captures():
    return jsonify(_captures(request.args.get("limit", 20, type=int)))


# ==================== HTML Template ====================

HTML = """
<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <title>ALPR YOLO Dashboard</title>
  <style>
    body{font-family:Arial,sans-serif;background:#0b0f16;color:#dce6f2;margin:0;padding:24px}
    h2{margin:0 0 16px}
    .hint{margin:0 0 16px;padding:10px 12px;border:1px solid #31415a;border-radius:8px;background:#122033;color:#b8c8dc}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:12px}
    .card{border:1px solid #223;background:#111b2a;border-radius:10px;overflow:hidden}
    .h{padding:8px 10px;border-bottom:1px solid #223;font-weight:700}
    .c{padding:8px}
    .c img{width:100%;display:block;min-height:220px;background:#05090f}
    .empty{padding:24px;border:1px dashed #31415a;border-radius:10px;background:#0f1826;color:#b8c8dc}
  </style>
</head>
<body>
  <h2>ALPR YOLO Monitor</h2>
  {% if not cameras %}
    <div class='empty'>
      <strong>No cameras available.</strong>
      <div style='margin-top:8px'>Please add/enable cameras in backend first, then refresh this page.</div>
    </div>
  {% else %}
    <p class='hint'>Showing {{ cameras|length }} camera(s). Streams update automatically.</p>
    <div class='grid'>
      {% for cam in cameras %}
      <div class='card'>
        <div class='h'>{{ cam.name or cam.id }}</div>
        <div class='c'><img src='/video/{{ cam.id }}' alt='Camera {{ cam.id }} stream'></div>
      </div>
      {% endfor %}
    </div>
  {% endif %}
</body>
</html>
"""


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
    )
    init_globals()
    # FIX: default port เปลี่ยนเป็น 5000 ให้ตรงกับ docker-compose.yml (เดิมเป็น 5001)
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()