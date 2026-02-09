import subprocess
from fastapi import APIRouter
from redis import Redis

from app.core.config import settings
from app.schemas.rtsp import RtspStartIn, RtspStopIn
from app.services.queue import enqueue_rtsp_ingest

router = APIRouter()

def _redis() -> Redis:
    return Redis.from_url(settings.redis_url)

def _stop_key(camera_id: str) -> str:
    return f"rtsp:stop:{camera_id}"

@router.post("/rtsp/start")
def rtsp_start(payload: RtspStartIn):
    r = _redis()
    r.delete(_stop_key(payload.camera_id))
    subprocess.Popen([
        "python", "-m", "alpr_worker.rtsp.frame_producer",
        "--camera-id", payload.camera_id,
        "--rtsp-url", payload.rtsp_url,
        "--fps", str(payload.fps),
    ])
    return {"ok": True, "camera_id": payload.camera_id}

@router.post("/rtsp/stop")
def rtsp_stop(payload: RtspStopIn):
    r = _redis()
    r.set(_stop_key(payload.camera_id), "1")
    return {"ok": True, "camera_id": payload.camera_id}
