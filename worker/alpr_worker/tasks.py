# worker/alpr_worker/tasks.py
import os
import time
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import bindparam
from sqlalchemy.dialects.postgresql import JSONB
from datetime import timezone
import cv2

from .celery_app import celery_app
from .rtsp_control import should_stop  # worker/rtsp_control.py

from .inference.detector import PlateDetector
from .inference.ocr import PlateOCR  # ใช้ OCR / parser ที่คุณมีอยู่แล้ว


# ----------------------------
# Env
# ----------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage"))
MASTER_CONF_THRESHOLD = float(os.getenv("MASTER_CONF_THRESHOLD", "0.95"))

# RTSP defaults
DEFAULT_RTSP_FPS = float(os.getenv("RTSP_FPS", "2.0"))
DEFAULT_RECONNECT_SEC = float(os.getenv("RTSP_RECONNECT_SEC", "2.0"))

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "original").mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "crops").mkdir(parents=True, exist_ok=True)


# ----------------------------
# DB
# ----------------------------
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now_utc() -> datetime:
    return datetime.utcnow()


# ----------------------------
# Singletons
# ----------------------------
_detector: Optional[PlateDetector] = None
_ocr: Optional[PlateOCR] = None


def get_detector() -> PlateDetector:
    global _detector
    if _detector is None:
        _detector = PlateDetector()
    return _detector


def get_ocr() -> PlateOCR:
    global _ocr
    if _ocr is None:
        _ocr = PlateOCR()
    return _ocr


# ----------------------------
# Core task: process_capture
# ----------------------------
@celery_app.task(name="tasks.process_capture")
def process_capture(capture_id: int, image_path: str):
    """
    Process one capture (image):
    - Detect plate (TensorRT .engine or YOLO fallback) -> crop
    - OCR -> plate_text + province + confidence
    - Insert into reads
    - Master logic:
        * if conf >= MASTER_CONF_THRESHOLD -> upsert master
        * else keep only in reads (still can be verified later)
    """
    img_path = Path(image_path)

    if not img_path.exists():
        return {"ok": False, "error": "image not found", "image_path": image_path}

    detector = get_detector()
    ocr = get_ocr()

    db = SessionLocal()
    try:
        # 1) detect + crop
        det = detector.detect_and_crop(str(img_path))
        crop_path = det.crop_path

        # 2) OCR
        # PlateOCR.read returns OCRResult dataclass with:
        #   - plate_text: detected plate number
        #   - province: detected province name
        #   - conf: confidence score (0..1)
        #   - raw: debug info
        o = ocr.read(crop_path)

        plate_text = (o.plate_text or "").strip()
        province = (o.province or "").strip()
        conf = float(o.conf or 0.0)
        raw = o.raw or {}

        # 3) write reads row
        sql_ins_read = text("""
            INSERT INTO plate_reads (
                capture_id,
                plate_crop_path,
                det_conf,
                ocr_conf,
                plate_text,
                province,
                status,
                created_at,
                det_meta,
                ocr_meta
            )
            VALUES (
                :capture_id,
                :plate_crop_path,
                :det_conf,
                :ocr_conf,
                :plate_text,
                :province,
                :status,
                :created_at,
                :det_meta,
                :ocr_meta
            )
            RETURNING id
        """).bindparams(
            bindparam("det_meta", type_=JSONB),
            bindparam("ocr_meta", type_=JSONB),
        )

        # status default = PENDING (รอคนตรวจ)
        read_id = db.execute(sql_ins_read, {
            "capture_id": int(capture_id),
            "plate_crop_path": str(crop_path),
            "det_conf": float(det.det_conf),
            "ocr_conf": conf,
            "plate_text": plate_text,
            "province": province,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc),
            "det_meta": det.bbox or {},
            "ocr_meta": raw or {},
        }).scalar_one()
        db.commit()

        # 4) master logic (ถ้า conf >= threshold ให้ upsert master)
        if conf >= MASTER_CONF_THRESHOLD and plate_text:
            # master key: plate_text + province
            sql_upsert_master = text("""
                INSERT INTO master_plates (
                    plate_text,
                    province,
                    best_confidence,
                    last_seen_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    :plate_text,
                    :province,
                    :best_confidence,
                    :last_seen_at,
                    :created_at,
                    :updated_at
                )
                ON CONFLICT (plate_text, province)
                DO UPDATE SET
                    best_confidence = GREATEST(master_plates.best_confidence, EXCLUDED.best_confidence),
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = EXCLUDED.updated_at
            """)
            db.execute(sql_upsert_master, {
                "plate_text": plate_text,
                "province": province,
                "best_confidence": conf,
                "last_seen_at": now_utc(),
                "created_at": now_utc(),
                "updated_at": now_utc(),
            })
            db.commit()

        return {
            "ok": True,
            "capture_id": capture_id,
            "read_id": int(read_id),
            "plate_text": plate_text,
            "province": province,
            "confidence": conf,
            "crop_path": str(crop_path),
        }

    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e), "capture_id": capture_id, "image_path": image_path}
    finally:
        db.close()


# ----------------------------
# RTSP ingest task
# ----------------------------
@celery_app.task(name="tasks.rtsp_ingest")
def rtsp_ingest(camera_id: str, rtsp_url: str, fps: float = DEFAULT_RTSP_FPS, reconnect_sec: float = DEFAULT_RECONNECT_SEC):
    """
    Long-running RTSP ingest:
    - Reads stream via OpenCV FFmpeg backend
    - Samples frames at target fps
    - Saves frame -> inserts captures row -> enqueue process_capture
    - Stops when Redis stop flag is set (rtsp:stop:{camera_id} == 1)
    """

    fps = float(fps or DEFAULT_RTSP_FPS)
    reconnect_sec = float(reconnect_sec or DEFAULT_RECONNECT_SEC)
    interval = 1.0 / max(fps, 0.1)

    cap = None
    last_ts = 0.0

    while True:
        # stop flag
        if should_stop(camera_id):
            if cap is not None:
                cap.release()
            return {"ok": True, "stopped": True, "camera_id": camera_id}

        # open stream
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                time.sleep(reconnect_sec)
                continue

        ok, frame = cap.read()
        if not ok or frame is None:
            # reconnect
            cap.release()
            cap = None
            time.sleep(reconnect_sec)
            continue

        now = time.time()
        if (now - last_ts) < interval:
            continue
        last_ts = now

        # save frame
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        out_path = STORAGE_DIR / "original" / f"rtsp_{camera_id}_{ts}.jpg"
        cv2.imwrite(str(out_path), frame)

        # insert capture
        db = SessionLocal()
        try:
            digest = sha256_file(out_path)

            sql_ins_cap = text("""
                INSERT INTO captures (
                    source,
                    camera_id,
                    captured_at,
                    original_path,
                    sha256
                )
                VALUES (
                    :source,
                    :camera_id,
                    :captured_at,
                    :original_path,
                    :sha256
                )
                RETURNING id
            """)

            cap_id = db.execute(sql_ins_cap, {
                "source": "RTSP",
                "camera_id": camera_id,
                "captured_at": now_utc(),
                "original_path": str(out_path),
                "sha256": digest,
            }).scalar_one()
            db.commit()

            # enqueue processing
            process_capture.delay(int(cap_id), str(out_path))

        except Exception:
            db.rollback()
        finally:
            db.close()
