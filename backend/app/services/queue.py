import logging

from celery import Celery
from app.core.config import settings

celery = Celery("alpr_api", broker=settings.redis_url)
logger = logging.getLogger(__name__)

def enqueue_process_capture(capture_id: int, image_path: str):
    try:
        celery.send_task("tasks.process_capture", args=[capture_id, image_path])
        return True
    except Exception:
        logger.exception("Failed to enqueue process_capture", extra={"capture_id": capture_id, "image_path": image_path})
        return False

def enqueue_rtsp_ingest(camera_id: str, rtsp_url: str, fps: float, reconnect_sec: float):
    return celery.send_task(
        "tasks.rtsp_ingest",
        args=[camera_id, rtsp_url, fps, reconnect_sec],
    )
