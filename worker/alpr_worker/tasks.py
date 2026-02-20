# worker/alpr_worker/tasks.py
import os
import json
import base64
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
import cv2
import numpy as np
import re

from .celery_app import celery_app
from .inference.ocr import PlateOCR
from .inference.master_lookup import assist_with_master

# --- TensorRT Detector Import ---
USE_TRT_DETECTOR = os.getenv("USE_TRT_DETECTOR", "false").lower() == "true"

if USE_TRT_DETECTOR:
    try:
        from .inference.trt.yolov8_trt_detector import YOLOv8TRTPlateDetector as PlateDetector
        log = logging.getLogger(__name__)
        log.info("Using TensorRT detector for plate detection")
    except ImportError as e:
        from .inference.detector import PlateDetector
        log = logging.getLogger(__name__)
        log.warning("TensorRT detector not available, falling back to Ultralytics: %s", e)
else:
    from .inference.detector import PlateDetector

# --- Crop Validator ---
try:
    from .inference.crop_validator import CropValidator
    _crop_validator: Optional[CropValidator] = None
    CROP_VALIDATOR_AVAILABLE = True
except ImportError:
    CROP_VALIDATOR_AVAILABLE = False
    _crop_validator = None


def get_crop_validator() -> Optional["CropValidator"]:
    global _crop_validator
    if not CROP_VALIDATOR_AVAILABLE:
        return None
    if _crop_validator is None:
        _crop_validator = CropValidator()
    return _crop_validator


# --- Plate Dedup ---
try:
    from .inference.plate_dedup import PlateDedup
    _plate_dedup: Optional[PlateDedup] = None
    PLATE_DEDUP_AVAILABLE = True
except ImportError:
    PLATE_DEDUP_AVAILABLE = False
    _plate_dedup = None


def get_plate_dedup() -> Optional["PlateDedup"]:
    global _plate_dedup
    if not PLATE_DEDUP_AVAILABLE:
        return None
    if _plate_dedup is None:
        from redis import Redis
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        redis_client = Redis.from_url(redis_url)
        _plate_dedup = PlateDedup(redis_client)
    return _plate_dedup


log = logging.getLogger(__name__)


# ----------------------------
# Env
# ----------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://alpr:alpr@postgres:5432/lpr_v2")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage"))
MASTER_CONF_THRESHOLD = float(os.getenv("MASTER_CONF_THRESHOLD", "0.95"))

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "original").mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "crops").mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "debug").mkdir(parents=True, exist_ok=True)


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
    """Get singleton plate detector (uses models/best.engine for TRT)"""
    global _detector
    if _detector is None:
        _detector = PlateDetector()
    return _detector


def get_ocr() -> PlateOCR:
    global _ocr
    if _ocr is None:
        _ocr = PlateOCR()
    return _ocr


def norm_plate_text(s: str) -> str:
    if not s:
        return ""
    s = s.strip().upper()
    s = s.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
    s = re.sub(r"[\s\-\.]", "", s)
    return s


@celery_app.task(name="tasks.process_lpr_task", bind=True, max_retries=3)
def process_lpr_task(
    self,
    vehicle_crop_b64: str,
    track_id: int,
    vehicle_count: int,
    camera_id: str,
):
    """
    Process LPR for a vehicle that crossed the counting line
    
    Args:
        vehicle_crop_b64: Base64-encoded vehicle crop image
        track_id: ByteTrack track ID
        vehicle_count: Sequential count number
        camera_id: Camera identifier
    
    Returns:
        Dict with processing results
    """
    log.info(
        "🚀 LPR TASK STARTED: track_id=%d, count=%d, camera=%s",
        track_id, vehicle_count, camera_id
    )
    
    db = SessionLocal()
    
    try:
        # =============================================
        # 1) DECODE BASE64 VEHICLE CROP
        # =============================================
        try:
            img_bytes = base64.b64decode(vehicle_crop_b64)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            vehicle_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            if vehicle_img is None or vehicle_img.size == 0:
                raise ValueError("Failed to decode vehicle crop image")
            
            log.debug(
                "Vehicle crop decoded: shape=%s, track_id=%d",
                vehicle_img.shape, track_id
            )
        except Exception as e:
            log.error("Failed to decode vehicle crop (track_id=%d): %s", track_id, e)
            return {
                "ok": False,
                "error": f"decode_failed:{str(e)}",
                "track_id": track_id,
                "vehicle_count": vehicle_count,
                "camera_id": camera_id,
            }
        
        # Save vehicle crop for debugging/records
        vehicle_crop_dir = STORAGE_DIR / "original" / "vehicle_crops"
        vehicle_crop_dir.mkdir(parents=True, exist_ok=True)
        vehicle_crop_path = vehicle_crop_dir / f"{camera_id}_{track_id}_{vehicle_count}.jpg"
        cv2.imwrite(str(vehicle_crop_path), vehicle_img)
        
        # =============================================
        # 2) DETECT LICENSE PLATE USING models/best.engine
        #    (TensorRT model for plate detection & crop)
        # =============================================
        detector = get_detector()
        
        try:
            # Save vehicle image to temp file for detector input
            temp_vehicle_path = STORAGE_DIR / "crops" / f"temp_vehicle_{track_id}.jpg"
            cv2.imwrite(str(temp_vehicle_path), vehicle_img)
            
            # Run plate detection (uses models/best.engine in TRT mode)
            det = detector.detect_and_crop(str(temp_vehicle_path))
            plate_crop_path = det.crop_path
            det_conf = det.det_conf
            
            log.info(
                "Plate detected: track_id=%d, conf=%.2f, crop=%s",
                track_id, det_conf, plate_crop_path
            )
            
            # Cleanup temp file
            if temp_vehicle_path.exists():
                temp_vehicle_path.unlink()
        
        except Exception as e:
            log.warning(
                "Plate detection failed for track_id=%d: %s",
                track_id, e
            )
            return {
                "ok": False,
                "error": f"detection_failed:{str(e)}",
                "track_id": track_id,
                "vehicle_count": vehicle_count,
                "camera_id": camera_id,
                "vehicle_crop_path": str(vehicle_crop_path),
            }
        
        # =============================================
        # 3) CROP VALIDATION
        # =============================================
        crop_validator = get_crop_validator()
        if crop_validator is not None:
            plate_crop_img = cv2.imread(plate_crop_path)
            if plate_crop_img is not None:
                val_result = crop_validator.validate(plate_crop_img)
                if not val_result.passed:
                    log.info(
                        "CropValidator REJECT track_id=%d: %s (aspect=%.2f size=%dx%d)",
                        track_id, val_result.reject_reason,
                        val_result.aspect_ratio, val_result.width, val_result.height,
                    )
                    return {
                        "ok": False,
                        "error": f"crop_rejected:{val_result.reject_reason}",
                        "track_id": track_id,
                        "vehicle_count": vehicle_count,
                        "camera_id": camera_id,
                        "vehicle_crop_path": str(vehicle_crop_path),
                        "crop_validation": {
                            "aspect_ratio": val_result.aspect_ratio,
                            "width": val_result.width,
                            "height": val_result.height,
                            "contrast": val_result.contrast,
                            "edge_density": val_result.edge_density,
                        },
                    }
        
        # =============================================
        # 4) OCR PLATE TEXT
        # =============================================
        ocr = get_ocr()
        o = ocr.read_plate(
            plate_crop_path,
            debug_dir=STORAGE_DIR / "debug",
            debug_id=f"{camera_id}_{track_id}_{vehicle_count}",
        )
        
        plate_text = (o.plate_text or "").strip()
        province = (o.province or "").strip()
        conf = float(o.confidence or 0.0)
        raw = o.raw or {}
        
        plate_text_norm = norm_plate_text(plate_text)
        
        # Master lookup assistance
        assisted = assist_with_master(db, plate_text, province, conf)
        plate_text = assisted["plate_text"]
        plate_text_norm = assisted["plate_text_norm"]
        province = assisted["province"]
        conf = float(assisted["confidence"])
        
        if conf < 0.6:
            log.warning(
                "Low OCR confidence for track_id=%d variant=%s candidates=%s",
                track_id,
                raw.get("chosen_variant"),
                raw.get("candidates"),
            )
        
        # =============================================
        # 5) PLATE DEDUP CHECK
        # =============================================
        plate_dedup = get_plate_dedup()
        if plate_dedup is not None and plate_text_norm:
            dedup_result = plate_dedup.check(
                plate_text_norm=plate_text_norm,
                confidence=conf,
                capture_id=track_id,  # Using track_id as pseudo capture_id
                camera_id=camera_id,
            )
            
            if dedup_result.is_duplicate and dedup_result.action == "skip":
                log.info(
                    "PlateDedup SKIP track_id=%d plate=%s "
                    "(existing_cap=%s conf=%.2f >= new_conf=%.2f)",
                    track_id, plate_text_norm,
                    dedup_result.existing_capture_id,
                    dedup_result.existing_confidence,
                    conf,
                )
                return {
                    "ok": False,
                    "error": "plate_duplicate:skip",
                    "track_id": track_id,
                    "vehicle_count": vehicle_count,
                    "camera_id": camera_id,
                    "plate_text_norm": plate_text_norm,
                    "existing_confidence": dedup_result.existing_confidence,
                    "new_confidence": conf,
                }
        
        # =============================================
        # 6) INSERT CAPTURES RECORD
        # =============================================
        capture_id = db.execute(
            text("""
                INSERT INTO captures (
                    source, camera_id, track_id, captured_at,
                    original_path, sha256
                )
                VALUES (
                    :source, :camera_id, :track_id, :captured_at,
                    :original_path, :sha256
                )
                RETURNING id
            """),
            {
                "source": "LINE_CROSSING",
                "camera_id": camera_id,
                "track_id": track_id,
                "captured_at": datetime.now(timezone.utc),
                "original_path": str(vehicle_crop_path),
                "sha256": sha256_file(vehicle_crop_path),
            },
        ).scalar_one()
        
        # =============================================
        # 7) INSERT DETECTIONS RECORD
        # =============================================
        detection_id = db.execute(
            text("""
                INSERT INTO detections (capture_id, crop_path, det_conf, bbox)
                VALUES (:capture_id, :crop_path, :det_conf, :bbox)
                RETURNING id
            """),
            {
                "capture_id": int(capture_id),
                "crop_path": str(plate_crop_path),
                "det_conf": float(det_conf),
                "bbox": json.dumps(det.bbox or {}, ensure_ascii=False),
            },
        ).scalar_one()
        
        # =============================================
        # 8) INSERT PLATE_READS RECORD
        # =============================================
        read_id = db.execute(
            text("""
                INSERT INTO plate_reads (
                    detection_id, plate_text, plate_text_norm,
                    province, confidence, status, created_at
                )
                VALUES (
                    :detection_id, :plate_text, :plate_text_norm,
                    :province, :confidence, :status, :created_at
                )
                RETURNING id
            """),
            {
                "detection_id": int(detection_id),
                "plate_text": (plate_text[:32] if plate_text else ""),
                "plate_text_norm": (plate_text_norm[:32] if plate_text_norm else ""),
                "province": (province[:64] if province else ""),
                "confidence": conf,
                "status": "PENDING",
                "created_at": datetime.now(timezone.utc),
            },
        ).scalar_one()
        
        db.commit()
        
        # =============================================
        # 9) MASTER PLATE UPSERT
        # =============================================
        if conf >= MASTER_CONF_THRESHOLD and plate_text_norm:
            db.execute(
                text("""
                    INSERT INTO master_plates (
                        plate_text_norm, display_text, province,
                        confidence, last_seen, count_seen, editable
                    )
                    VALUES (
                        :plate_text_norm, :display_text, :province,
                        :confidence, :last_seen, :count_seen, :editable
                    )
                    ON CONFLICT (plate_text_norm)
                    DO UPDATE SET
                        display_text = CASE
                            WHEN master_plates.display_text = '' AND EXCLUDED.display_text <> ''
                                THEN EXCLUDED.display_text
                            ELSE master_plates.display_text
                        END,
                        province = CASE
                            WHEN EXCLUDED.province <> '' THEN EXCLUDED.province
                            ELSE master_plates.province
                        END,
                        confidence = GREATEST(master_plates.confidence, EXCLUDED.confidence),
                        last_seen = EXCLUDED.last_seen,
                        count_seen = master_plates.count_seen + 1
                """),
                {
                    "plate_text_norm": plate_text_norm,
                    "display_text": (plate_text[:32] if plate_text else plate_text_norm),
                    "province": province,
                    "confidence": conf,
                    "last_seen": now_utc(),
                    "count_seen": 1,
                    "editable": True,
                },
            )
            db.commit()
        
        log.info(
            "✅ LPR SUCCESS: track_id=%d, count=%d, plate=%s, conf=%.2f",
            track_id, vehicle_count, plate_text, conf
        )
        
        return {
            "ok": True,
            "track_id": track_id,
            "vehicle_count": vehicle_count,
            "camera_id": camera_id,
            "capture_id": int(capture_id),
            "detection_id": int(detection_id),
            "read_id": int(read_id),
            "plate_text": plate_text,
            "plate_text_norm": plate_text_norm,
            "province": province,
            "confidence": conf,
            "master_assisted": assisted.get("assisted", False),
            "vehicle_crop_path": str(vehicle_crop_path),
            "plate_crop_path": str(plate_crop_path),
        }
    
    except Exception as e:
        db.rollback()
        log.exception(
            "LPR task failed for track_id=%d, count=%d: %s",
            track_id, vehicle_count, e
        )
        
        # Retry logic
        try:
            raise self.retry(exc=e, countdown=5)
        except self.MaxRetriesExceededError:
            log.error("Max retries exceeded for track_id=%d", track_id)
        
        return {
            "ok": False,
            "error": str(e),
            "track_id": track_id,
            "vehicle_count": vehicle_count,
            "camera_id": camera_id,
        }
    
    finally:
        db.close()