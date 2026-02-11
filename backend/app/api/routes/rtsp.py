import subprocess
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi import HTTPException
from redis import Redis
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.schemas.rtsp import RtspStartIn, RtspStopIn
from app.services.queue import enqueue_rtsp_ingest

router = APIRouter()

def _camera_stream_dir(camera_id: str) -> Path:
    return Path(settings.storage_dir) / "rtsp" / camera_id


def _latest_jpg(camera_id: str) -> Path | None:
    stream_dir = _camera_stream_dir(camera_id)
    if not stream_dir.exists() or not stream_dir.is_dir():
        return None
    images = [p for p in stream_dir.glob("*.jpg") if p.is_file()]
    if not images:
        return None
    return max(images, key=lambda p: p.stat().st_mtime)

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

@router.get("/streams/{camera_id}/mjpeg")
def stream_mjpeg(camera_id: str):
    latest = _latest_jpg(camera_id)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"No stream frames for camera '{camera_id}'")

    def iter_frames():
        boundary = b"frame"
        last_mtime_ns = 0
        while True:
            frame_path = _latest_jpg(camera_id)
            if frame_path is None:
                time.sleep(0.2)
                continue

            stat = frame_path.stat()
            if stat.st_mtime_ns == last_mtime_ns:
                time.sleep(0.08)
                continue

            with frame_path.open("rb") as f:
                jpg = f.read()

            last_mtime_ns = stat.st_mtime_ns
            yield b"--" + boundary + b"\r\n"
            yield b"Content-Type: image/jpeg\r\n"
            yield f"Content-Length: {len(jpg)}\r\n\r\n".encode("ascii")
            yield jpg
            yield b"\r\n"

    return StreamingResponse(
        iter_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )