import os
from celery import Celery
from app.core.config import settings

celery = Celery("alpr_api", broker=settings.redis_url)

def enqueue_process_capture(capture_id: int, image_path: str):
    celery.send_task("tasks.process_capture", args=[capture_id, image_path])

def enqueue_rtsp_ingest(camera_id: str, rtsp_url: str, fps: float, reconnect_sec: float):
    return celery.send_task(
        "tasks.rtsp_ingest",
        args=[camera_id, rtsp_url, fps, reconnect_sec],
    )
