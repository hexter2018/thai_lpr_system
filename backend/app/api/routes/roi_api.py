"""
roi_api.py — FastAPI Router สำหรับ ROI Agent Dashboard
========================================================

Safety:
  - Feature flag: ROI_API_ENABLED=false ปิดทั้ง router
  - ROI validation: range, area, width, height
  - Rate limit: POST max 10/min per camera
  - History: เก็บ 10 versions → rollback ได้
  - SSRF protection: camera_id ต้องอยู่ใน config
  - Snapshot timeout: ffmpeg 10s
  - RTSP credentials masked ใน response

Deploy:
  1. Copy → backend/app/api/routers/roi_api.py
  2. main.py เพิ่ม:
       from app.api.routers.roi_api import router as roi_router
       app.include_router(roi_router)
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)

ROI_API_ENABLED = os.getenv("ROI_API_ENABLED", "true").lower() == "true"

router = APIRouter(prefix="/api/roi-agent", tags=["roi-agent"])

# ─── REDIS (lazy, safe) ──────────────────────────────────────
_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.Redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        log.warning("ROI API: Redis failed: %s", e)
        return None

# ─── CAMERAS CONFIG ───────────────────────────────────────────
def _get_cameras_config() -> List[Dict]:
    raw = os.getenv("CAMERAS_CONFIG", "[]")
    try:
        cameras = json.loads(raw)
        return cameras if isinstance(cameras, list) else []
    except json.JSONDecodeError:
        return []

# ─── RATE LIMITER ─────────────────────────────────────────────
_rate_limit: Dict[str, List[float]] = {}

def _check_rate_limit(camera_id: str, max_req: int = 10, window: int = 60) -> bool:
    now = time.time()
    key = f"roi:{camera_id}"
    if key not in _rate_limit:
        _rate_limit[key] = []
    _rate_limit[key] = [t for t in _rate_limit[key] if now - t < window]
    if len(_rate_limit[key]) >= max_req:
        return False
    _rate_limit[key].append(now)
    return True

# ─── REDIS KEYS ───────────────────────────────────────────────
def _roi_key(cid): return f"alpr:roi:{cid}"
def _history_key(cid): return f"alpr:roi_history:{cid}"
def _heartbeat_key(cid): return f"alpr:camera_heartbeat:{cid}"

# ─── MODELS ───────────────────────────────────────────────────
class ROIConfig(BaseModel):
    x1: float; y1: float; x2: float; y2: float

    @field_validator("x1", "y1", "x2", "y2")
    @classmethod
    def validate_range(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Value {v} must be 0.0-1.0")
        return round(v, 4)

class CameraInfo(BaseModel):
    id: str
    name: str
    rtsp_masked: str = ""
    status: str = "unknown"
    roi: Optional[ROIConfig] = None
    roi_source: str = "none"

class ROIUpdateResponse(BaseModel):
    ok: bool
    camera_id: str
    roi: ROIConfig
    message: str
    previous_roi: Optional[ROIConfig] = None
    history_count: int = 0

# ─── SAFETY HELPERS ───────────────────────────────────────────
def _guard():
    if not ROI_API_ENABLED:
        raise HTTPException(503, "ROI API disabled. Set ROI_API_ENABLED=true")

def _validate_roi(roi: ROIConfig) -> Optional[str]:
    if roi.x1 >= roi.x2: return f"x1 ({roi.x1}) >= x2 ({roi.x2})"
    if roi.y1 >= roi.y2: return f"y1 ({roi.y1}) >= y2 ({roi.y2})"
    area = (roi.x2 - roi.x1) * (roi.y2 - roi.y1)
    if area < 0.05: return f"Area {area:.3f} too small (min 5%)"
    if (roi.x2 - roi.x1) < 0.10: return "Width too narrow (min 10%)"
    if (roi.y2 - roi.y1) < 0.10: return "Height too short (min 10%)"
    return None

def _mask_rtsp(url: str) -> str:
    if "@" in url:
        parts = url.split("@", 1)
        return f"rtsp://***@{parts[1]}" if len(parts) > 1 else "rtsp://***"
    return url

def _save_history(r, camera_id: str, roi_data: Dict):
    try:
        r.lpush(_history_key(camera_id), json.dumps(roi_data))
        r.ltrim(_history_key(camera_id), 0, 9)
    except Exception:
        pass

# ─── ENDPOINTS ────────────────────────────────────────────────

@router.get("/health")
async def health():
    """Health check — ไม่ต้อง guard (ใช้ monitor ได้เสมอ)"""
    r = _get_redis()
    cameras = _get_cameras_config()
    return {
        "api_enabled": ROI_API_ENABLED,
        "redis_connected": r is not None,
        "cameras_configured": len(cameras),
    }

@router.get("/cameras", response_model=List[CameraInfo])
async def list_cameras():
    _guard()
    cameras = _get_cameras_config()
    r = _get_redis()
    result = []
    for cam in cameras:
        cid = cam.get("id", "")
        roi, roi_source = None, "none"
        status = "unknown"
        if r:
            try:
                raw = r.get(_roi_key(cid))
                if raw:
                    d = json.loads(raw)
                    roi = ROIConfig(x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])
                    roi_source = "redis"
            except Exception:
                pass
            try:
                hb = r.get(_heartbeat_key(cid))
                if hb:
                    status = "online" if time.time() - float(hb) < 30 else "stale"
                else:
                    status = "no_heartbeat"
            except Exception:
                pass
        result.append(CameraInfo(
            id=cid, name=cam.get("name", cid),
            rtsp_masked=_mask_rtsp(cam.get("rtsp", "")),
            status=status, roi=roi, roi_source=roi_source,
        ))
    return result

@router.get("/snapshot/{camera_id}")
async def snapshot(camera_id: str, width: int = 1280):
    """Capture 1 frame — SSRF protected, timeout 10s"""
    _guard()
    cameras = _get_cameras_config()
    cam = next((c for c in cameras if c.get("id") == camera_id), None)
    if not cam:
        raise HTTPException(404, f"Camera '{camera_id}' not in config")
    rtsp_url = cam.get("rtsp", "")
    if not rtsp_url:
        raise HTTPException(400, "No RTSP URL")
    width = min(max(width, 320), 1920)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        cmd = [
            "ffmpeg", "-y", "-rtsp_transport", "tcp",
            "-i", rtsp_url, "-frames:v", "1",
            "-vf", f"scale={width}:-1", "-q:v", "2", "-f", "image2", tmp_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
            if stderr:
                log.warning("ROI snapshot ffmpeg failed for %s: %s", camera_id, stderr[-500:])
            raise HTTPException(502, "Snapshot failed — camera may be offline")
        with open(tmp_path, "rb") as f:
            jpeg = f.read()
        if len(jpeg) < 1000:
            raise HTTPException(502, "Snapshot too small")
        r = _get_redis()
        if r:
            try: r.setex(_heartbeat_key(camera_id), 60, str(time.time()))
            except Exception: pass
        return Response(content=jpeg, media_type="image/jpeg",
                       headers={"Cache-Control": "no-cache"})
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "RTSP timeout (10s)")
    except FileNotFoundError:
        log.exception("ROI snapshot failed: ffmpeg binary not found")
        raise HTTPException(503, "Snapshot service unavailable (ffmpeg not installed)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except Exception: pass

@router.get("/config/{camera_id}", response_model=ROIConfig)
async def get_roi(camera_id: str):
    _guard()
    r = _get_redis()
    if r:
        try:
            raw = r.get(_roi_key(camera_id))
            if raw:
                d = json.loads(raw)
                return ROIConfig(x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])
        except Exception:
            pass
    return ROIConfig(x1=0.15, y1=0.30, x2=0.85, y2=0.80)

@router.post("/config/{camera_id}", response_model=ROIUpdateResponse)
async def set_roi(camera_id: str, roi: ROIConfig, request: Request):
    """Save ROI — validated, rate-limited, history-tracked"""
    _guard()
    # Camera must exist
    cameras = _get_cameras_config()
    if not any(c.get("id") == camera_id for c in cameras):
        raise HTTPException(404, f"Camera '{camera_id}' not in config")
    # Rate limit
    if not _check_rate_limit(camera_id):
        raise HTTPException(429, "Max 10 ROI updates/min")
    # Validate
    err = _validate_roi(roi)
    if err:
        raise HTTPException(400, err)
    # Redis required
    r = _get_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    try:
        # Read previous
        prev = None
        try:
            raw = r.get(_roi_key(camera_id))
            if raw:
                d = json.loads(raw)
                prev = ROIConfig(x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])
        except Exception:
            pass
        # Save
        roi_data = {
            "x1": roi.x1, "y1": roi.y1, "x2": roi.x2, "y2": roi.y2,
            "updated_at": time.time(), "camera_id": camera_id,
            "updated_by": request.client.host if request.client else "unknown",
        }
        r.set(_roi_key(camera_id), json.dumps(roi_data))
        _save_history(r, camera_id, roi_data)
        hcount = r.llen(_history_key(camera_id)) or 0
        # Notify producers
        try:
            r.publish("alpr:roi_updated", json.dumps({"camera_id": camera_id, "roi": roi.model_dump()}))
        except Exception:
            pass
        log.info("ROI set: %s → (%.2f,%.2f)→(%.2f,%.2f)", camera_id, roi.x1, roi.y1, roi.x2, roi.y2)
        return ROIUpdateResponse(
            ok=True, camera_id=camera_id, roi=roi,
            message=f"ROI updated for {camera_id}",
            previous_roi=prev, history_count=hcount,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/history/{camera_id}")
async def get_history(camera_id: str):
    _guard()
    r = _get_redis()
    if not r:
        return {"camera_id": camera_id, "history": []}
    try:
        raws = r.lrange(_history_key(camera_id), 0, 9)
        return {"camera_id": camera_id, "history": [json.loads(x) for x in raws]}
    except Exception as e:
        return {"camera_id": camera_id, "history": [], "error": str(e)}

@router.post("/rollback/{camera_id}/{version}")
async def rollback(camera_id: str, version: int):
    """Rollback to history version (0=latest, 9=oldest)"""
    _guard()
    if not (0 <= version <= 9):
        raise HTTPException(400, "Version 0-9")
    r = _get_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    try:
        raw = r.lindex(_history_key(camera_id), version)
        if not raw:
            raise HTTPException(404, f"No history v{version}")
        d = json.loads(raw)
        roi = ROIConfig(x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])
        roi_data = {"x1": roi.x1, "y1": roi.y1, "x2": roi.x2, "y2": roi.y2,
                    "updated_at": time.time(), "camera_id": camera_id,
                    "updated_by": f"rollback_v{version}"}
        r.set(_roi_key(camera_id), json.dumps(roi_data))
        _save_history(r, camera_id, roi_data)
        r.publish("alpr:roi_updated", json.dumps({"camera_id": camera_id, "roi": roi.model_dump()}))
        return {"ok": True, "camera_id": camera_id, "rolled_back_to": version, "roi": roi.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@router.delete("/config/{camera_id}")
async def delete_roi(camera_id: str):
    """Delete ROI → producer fallback to ENV"""
    _guard()
    r = _get_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    try:
        deleted = r.delete(_roi_key(camera_id))
        r.publish("alpr:roi_updated", json.dumps({"camera_id": camera_id, "action": "deleted"}))
        return {"ok": True, "deleted": deleted > 0, "message": "Fallback to ENV defaults"}
    except Exception as e:
        raise HTTPException(500, str(e))