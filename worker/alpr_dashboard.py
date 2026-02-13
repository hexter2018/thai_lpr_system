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

def _load_cameras_from_backend() -> List[Dict[str, Any]]:
    backend_api_url = os.getenv("BACKEND_API_URL", "http://backend:8000")
    endpoint = f"{backend_api_url.rstrip('/')}/api/cameras"

    try:
        with urlopen(endpoint, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Unable to load cameras from backend API (%s): %s", endpoint, exc)
        return []

    if not isinstance(payload, list):
        log.warning("Unexpected camera payload type from backend API: %s", type(payload).__name__)
        return []

    cameras: List[Dict[str, Any]] = []
    for camera in payload:
        if not isinstance(camera, dict):
            continue
        camera_id = camera.get("camera_id") or camera.get("id")
        if not camera_id:
            continue
        cameras.append({
            "id": camera_id,
            "name": camera.get("name") or camera_id,
        })

    return cameras

def init_globals():
    global redis_client, db_session_factory, zones_config, detector_info, cameras_config

    redis_client = None
    try:
        redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        redis_client.ping()
    except Exception as exc:
        log.warning("Redis unavailable: %s", exc)

    try:
        engine = create_engine(os.getenv("DATABASE_URL", "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr"), pool_pre_ping=True)
        db_session_factory = sessionmaker(bind=engine)
    except Exception as exc:
        log.warning("Database unavailable: %s", exc)

    if ALPR_MODULES_AVAILABLE and load_zones_from_env:
        try:
            zones_config = load_zones_from_env()
        except Exception:
            zones_config = []

    cameras_config = _load_cameras_from_backend()
    if not cameras_config:
        try:
            cameras_config = json.loads(os.getenv("CAMERAS_CONFIG", "[]"))
        except Exception:
            cameras_config = []

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
            d.vehicle_classes = [int(c.strip()) for c in os.getenv("VEHICLE_DETECTOR_CLASSES", "2,3,5,7").split(",")]
            detector_info = d.get_info()
        except Exception:
            detector_info = {}


def _get_frame(camera_id: str) -> Optional[bytes]:
    if not redis_client:
        return None
    try:
        return redis_client.get(f"alpr:yolo_preview:{camera_id}") or redis_client.get(f"alpr:preview:{camera_id}")
    except Exception:
        return None


def _placeholder(camera_id: str) -> bytes:
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(img, camera_id, (20, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (120, 120, 120), 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes() if ok else b""


def _gen(camera_id: str):
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
        rows = db.execute(text("""
            SELECT c.id, c.camera_id, c.captured_at, pr.plate_text, pr.confidence, pr.province
            FROM captures c
            LEFT JOIN detections d ON d.capture_id = c.id
            LEFT JOIN plate_reads pr ON pr.detection_id = d.id
            ORDER BY c.captured_at DESC LIMIT :limit
        """), {"limit": limit})
        return [{
            "id": r.id,
            "camera_id": r.camera_id or "",
            "captured_at": r.captured_at.isoformat() if r.captured_at else "",
            "plate_text": r.plate_text or "",
            "confidence": round(float(r.confidence or 0), 3),
            "province": r.province or "",
        } for r in rows]
    finally:
        db.close()


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
    hist.append({"t": int(time.time()), "yolo_triggers": stats.get("yolo_zone_triggers", 0), "enqueued": stats.get("frames_enqueued", 0)})
    stats["history"] = list(hist)[-20:]
    return jsonify(stats)


@app.route("/api/health")
def api_health():
    redis_ok = False
    db_ok = False
    try:
        if redis_client:
            redis_client.ping(); redis_ok = True
    except Exception:
        pass
    try:
        if db_session_factory:
            db = db_session_factory(); db.execute(text("SELECT 1")); db.close(); db_ok = True
    except Exception:
        pass
    return jsonify({"redis": redis_ok, "database": db_ok, "zones_count": len(zones_config), "cameras_count": len(cameras_config)})


@app.route("/api/zones")
def api_zones():
    return jsonify([{"name": z.name, "points": z.points, "min_fill_ratio": z.min_fill_ratio, "cooldown_sec": z.cooldown_sec} for z in zones_config])


@app.route("/api/detector")
def api_detector():
    return jsonify(detector_info)


@app.route("/api/captures")
def api_captures():
    return jsonify(_captures(request.args.get("limit", 20, type=int)))


HTML = """
<!doctype html><html><head><meta charset='utf-8'><title>ALPR YOLO Dashboard</title>
<style>body{font-family:Arial;background:#0b0f16;color:#dce6f2}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:12px}.card{border:1px solid #223;background:#111b2a}.h{padding:8px 10px;border-bottom:1px solid #223}.c{padding:8px}.c img{width:100%}</style>
</head><body><h2>ALPR YOLO Monitor</h2><div class='grid'>{% for cam in cameras %}<div class='card'><div class='h'>{{ cam.name or cam.id }}</div><div class='c'><img src='/video/{{ cam.id }}'></div></div>{% endfor %}</div></body></html>
"""


def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s")
    init_globals()
    port = int(os.getenv("DASHBOARD_PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
