import logging
from celery import Celery
from app.core.config import settings

celery = Celery("alpr_api", broker=settings.redis_url)
logger = logging.getLogger(__name__)

def enqueue_process_capture(capture_id: int, image_path: str):
    """Enqueue capture processing task to LPR queue"""
    try:
        celery.send_task(
            "tasks.process_capture",
            args=[capture_id, image_path],
            queue="lpr"  # ✅ Worker listens on 'lpr' queue
        )
        logger.info("Enqueued capture %d to LPR queue", capture_id)
        return True
    except Exception:
        logger.exception(
            "Failed to enqueue process_capture",
            extra={"capture_id": capture_id, "image_path": image_path}
        )
        return False

def enqueue_rtsp_ingest(camera_id: str, rtsp_url: str, fps: float, reconnect_sec: float):
    """Enqueue RTSP ingestion task to tracking queue"""
    try:
        return celery.send_task(
            "tasks.rtsp_ingest",
            args=[camera_id, rtsp_url, fps, reconnect_sec],
            queue="tracking"  # ✅ Worker listens on 'tracking' queue
        )
    except Exception:
        logger.exception("Failed to enqueue rtsp_ingest", extra={"camera_id": camera_id})
        return None
