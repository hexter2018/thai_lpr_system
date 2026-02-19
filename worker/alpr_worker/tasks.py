# worker/alpr_worker/tasks.py
import os
import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from datetime import timezone
import cv2
import re
import logging

from .celery_app import celery_app
from .inference.detector import PlateDetector
from .inference.ocr import PlateOCR
from .inference.master_lookup import assist_with_master

# --- Crop Validator (กรอง crop ข้างรถ / เล็กเกิน / aspect ผิด) ---
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


# --- Plate Dedup (กรองทะเบียนซ้ำภายใน cooldown period) ---
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
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage"))
MASTER_CONF_THRESHOLD = float(os.getenv("MASTER_CONF_THRESHOLD", "0.95"))
FEEDBACK_EXPORT_LIMIT = int(os.getenv("FEEDBACK_EXPORT_LIMIT", "200"))
TRAINING_DIR = Path(os.getenv("TRAINING_DIR", str(STORAGE_DIR / "training")))

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "original").mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "crops").mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "debug").mkdir(parents=True, exist_ok=True)
TRAINING_DIR.mkdir(parents=True, exist_ok=True)


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


def norm_plate_text(s: str) -> str:
    if not s:
        return ""
    s = s.strip().upper()
    s = s.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
    s = re.sub(r"[\s\-\.]", "", s)
    return s


@celery_app.task(name="tasks.process_capture")
def process_capture(capture_id: int, image_path: str):
    log.info("🚀 TASK STARTED: capture_id=%s, image_path=%s", capture_id, image_path)
    img_path = Path(image_path)

    if not img_path.exists():
        return {"ok": False, "error": "image not found", "image_path": image_path}

    detector = get_detector()
    ocr = get_ocr()

    db = SessionLocal()
    try:
        # =============================================
        # 1) DETECT + CROP
        # =============================================
        det = detector.detect_and_crop(str(img_path))
        crop_path = det.crop_path

        # =============================================
        # 2) CROP VALIDATION
        #    กรอง crop ที่ไม่ใช่ป้ายจริง (ข้างรถ / เล็กเกิน / aspect ผิด)
        # =============================================
        crop_validator = get_crop_validator()
        if crop_validator is not None:
            crop_img_for_val = cv2.imread(crop_path)
            if crop_img_for_val is not None:
                val_result = crop_validator.validate(crop_img_for_val)
                if not val_result.passed:
                    log.info(
                        "CropValidator REJECT capture_id=%s: %s (aspect=%.2f size=%dx%d)",
                        capture_id, val_result.reject_reason,
                        val_result.aspect_ratio, val_result.width, val_result.height,
                    )
                    return {
                        "ok": False,
                        "error": f"crop_rejected:{val_result.reject_reason}",
                        "capture_id": capture_id,
                        "image_path": image_path,
                        "crop_validation": {
                            "aspect_ratio": val_result.aspect_ratio,
                            "width": val_result.width,
                            "height": val_result.height,
                            "contrast": val_result.contrast,
                            "edge_density": val_result.edge_density,
                            "is_side_view": val_result.is_side_view,
                        },
                    }

        # =============================================
        # 3) OCR
        # =============================================
        o = ocr.read_plate(
            crop_path,
            debug_dir=STORAGE_DIR / "debug",
            debug_id=str(capture_id),
        )
        plate_text = (o.plate_text or "").strip()
        province = (o.province or "").strip()
        conf = float(o.confidence or 0.0)
        raw = o.raw or {}

        plate_text_norm = norm_plate_text(plate_text)

        assisted = assist_with_master(db, plate_text, province, conf)
        plate_text = assisted["plate_text"]
        plate_text_norm = assisted["plate_text_norm"]
        province = assisted["province"]
        conf = float(assisted["confidence"])

        if conf < 0.6:
            log.warning(
                "Low OCR confidence for capture_id=%s variant=%s candidates=%s",
                capture_id,
                raw.get("chosen_variant"),
                raw.get("candidates"),
            )

        # =============================================
        # 4) PLATE DEDUP
        #    กรองทะเบียนเดียวกันที่เข้ามาซ้ำภายใน cooldown period
        # =============================================
        plate_dedup = get_plate_dedup()
        camera_id = ""
        try:
            row = db.execute(
                text("SELECT camera_id FROM captures WHERE id = :id"),
                {"id": int(capture_id)},
            ).fetchone()
            if row and row[0]:
                camera_id = str(row[0])
        except Exception as e:
            log.debug("Could not fetch camera_id for dedup: %s", e)

        if plate_dedup is not None and plate_text_norm:
            dedup_result = plate_dedup.check(
                plate_text_norm=plate_text_norm,
                confidence=conf,
                capture_id=int(capture_id),
                camera_id=camera_id,
            )

            if dedup_result.is_duplicate:
                if dedup_result.action == "skip":
                    log.info(
                        "PlateDedup SKIP capture_id=%s plate=%s "
                        "(existing_cap=%s conf=%.2f >= new_conf=%.2f)",
                        capture_id, plate_text_norm,
                        dedup_result.existing_capture_id,
                        dedup_result.existing_confidence,
                        conf,
                    )
                    return {
                        "ok": False,
                        "error": "plate_duplicate:skip",
                        "capture_id": capture_id,
                        "plate_text_norm": plate_text_norm,
                        "existing_capture_id": dedup_result.existing_capture_id,
                        "existing_confidence": dedup_result.existing_confidence,
                        "new_confidence": conf,
                        "reason": dedup_result.reason,
                    }
                elif dedup_result.action == "update":
                    # conf ใหม่สูงกว่า — insert ตามปกติ (Redis key อัปเดตแล้วใน PlateDedup)
                    log.info(
                        "PlateDedup UPDATE capture_id=%s plate=%s "
                        "(old_cap=%s conf=%.2f -> new_conf=%.2f)",
                        capture_id, plate_text_norm,
                        dedup_result.existing_capture_id,
                        dedup_result.existing_confidence,
                        conf,
                    )

        # =============================================
        # 5) INSERT detections
        # =============================================
        detection_id = db.execute(
            text("""
                INSERT INTO detections (capture_id, crop_path, det_conf, bbox)
                VALUES (:capture_id, :crop_path, :det_conf, :bbox)
                RETURNING id
            """),
            {
                "capture_id": int(capture_id),
                "crop_path": str(crop_path),
                "det_conf": float(det.det_conf),
                "bbox": json.dumps(det.bbox or {}, ensure_ascii=False),
            },
        ).scalar_one()

        # =============================================
        # 6) INSERT plate_reads
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
        # 7) MASTER PLATE UPSERT
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

        return {
            "ok": True,
            "capture_id": int(capture_id),
            "detection_id": int(detection_id),
            "read_id": int(read_id),
            "plate_text": plate_text,
            "plate_text_norm": plate_text_norm,
            "province": province,
            "confidence": conf,
            "master_assisted": assisted.get("assisted", False),
            "crop_path": str(crop_path),
            "plate_candidates": raw.get("plate_candidates", []),
            "province_candidates": raw.get("province_candidates", []),
            "consensus_metrics": raw.get("consensus_metrics", {}),
            "confidence_flags": raw.get("confidence_flags", []),
            "debug_flags": raw.get("debug_flags", []),
            "debug_artifacts": raw.get("debug_artifacts", {}),
        }

    except Exception as e:
        db.rollback()
        return {
            "ok": False,
            "error": str(e),
            "capture_id": capture_id,
            "image_path": image_path,
        }
    finally:
        db.close()


@celery_app.task(name="tasks.export_feedback_samples")
def export_feedback_samples(limit: int = FEEDBACK_EXPORT_LIMIT):
    """Export verified feedback samples เพื่อใช้ใน training"""
    images_dir = TRAINING_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = TRAINING_DIR / "manifest.jsonl"

    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT id, crop_path, corrected_text, corrected_province
                FROM feedback_samples
                WHERE used_in_train = false
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"limit": int(limit)},
        ).mappings().all()

        if not rows:
            return {"ok": True, "exported": 0}

        with manifest_path.open("a", encoding="utf-8") as f:
            for row in rows:
                src = Path(row["crop_path"])
                if not src.exists():
                    continue
                dst = images_dir / f"feedback_{row['id']}{src.suffix or '.jpg'}"
                if not dst.exists():
                    shutil.copy2(src, dst)
                f.write(json.dumps({
                    "image": str(dst),
                    "plate_text": row["corrected_text"],
                    "province": row["corrected_province"],
                    "source": "MLPR",
                }, ensure_ascii=False) + "\n")

        db.execute(
            text("UPDATE feedback_samples SET used_in_train = true WHERE id = ANY(:ids)"),
            {"ids": [int(r["id"]) for r in rows]},
        )
        db.commit()
        return {"ok": True, "exported": len(rows), "manifest": str(manifest_path)}

    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()