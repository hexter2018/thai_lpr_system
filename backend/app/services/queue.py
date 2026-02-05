import os
from celery import Celery
from app.core.config import settings

celery = Celery("alpr_api", broker=settings.redis_url)

def enqueue_process_capture(capture_id: int, image_path: str):
    celery.send_task("tasks.process_capture", args=[capture_id, image_path])
