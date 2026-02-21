import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "alpr_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

# ✅ แก้ไขส่วนนี้ - ระบุ module ที่มี tasks ชัดเจน
celery_app.autodiscover_tasks(["alpr_worker"], force=True)

# ✅ เพิ่ม config เพิ่มเติมสำหรับ production
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Bangkok",
    enable_utc=True,
    
    # ✅ เพิ่มส่วนนี้
    task_track_started=True,
    task_time_limit=300,  # 5 minutes timeout
    task_soft_time_limit=240,  # 4 minutes soft limit
    worker_prefetch_multiplier=4,  # จำนวน task ที่ worker รับล่วงหน้า
    worker_max_tasks_per_child=100,  # Restart worker หลังทำ 100 tasks (ป้องกัน memory leak)
    
    # ✅ Retry settings
    task_acks_late=True,  # Acknowledge task หลังทำเสร็จ (ถ้า crash จะได้ retry)
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    
    # ✅ Result backend settings
    result_expires=3600,  # เก็บ result 1 ชั่วโมง
    result_backend_transport_options={
        'master_name': 'mymaster',
        'visibility_timeout': 3600,
    },
)

# ✅ เพิ่มส่วนนี้ - ระบุ routing สำหรับแต่ละ task
celery_app.conf.task_routes = {
    'tasks.process_lpr_task': {'queue': 'lpr'},
    'tasks.process_capture': {'queue': 'lpr'},  # ถ้ายังมี task เดิม
    'tasks.export_feedback_samples': {'queue': 'training'},
}