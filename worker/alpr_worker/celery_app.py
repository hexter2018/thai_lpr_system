import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "alpr_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

# ✅ ให้ Celery ไปหา tasks ใน package นี้
celery_app.autodiscover_tasks(["alpr_worker"])

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Bangkok",
    enable_utc=True,
)
