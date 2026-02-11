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

    latest: Path | None = None
    latest_mtime_ns = -1
    for image_path in stream_dir.glob("*.jpg"):
        try:
            stat = image_path.stat()
        except FileNotFoundError:
            # Writer/worker can rotate temporary files while we're scanning.
            continue

        if not image_path.is_file():
            continue

        if stat.st_mtime_ns > latest_mtime_ns:
            latest = image_path
            latest_mtime_ns = stat.st_mtime_ns

    if latest is None:
        return None

    return latest

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

            try:
                stat = frame_path.stat()
            except FileNotFoundError:
                # File disappeared between lookup and stat; try the next frame.
                time.sleep(0.05)
                continue

            if stat.st_mtime_ns == last_mtime_ns:
                time.sleep(0.08)
                continue

            try:
                with frame_path.open("rb") as f:
                    jpg = f.read()
            except FileNotFoundError:
                # File disappeared between stat and open; try the next frame.
                time.sleep(0.05)
                continue

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
