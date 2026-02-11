# worker/alpr_worker/tasks.py
import os
import time
import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from datetime import timezone
import cv2
import re
import logging
from .celery_app import celery_app
from .rtsp_control import should_stop  # worker/rtsp_control.py

from .inference.detector import PlateDetector

# --- Headlight Deglare (ลด glare จากไฟหน้ารถกลางคืน) ---
try:
    from .rtsp.deglare import HeadlightDeglare
    _deglare: Optional[HeadlightDeglare] = None
    DEGLARE_AVAILABLE = True
except ImportError:
    DEGLARE_AVAILABLE = False
    _deglare = None
    logging.getLogger(__name__).warning("HeadlightDeglare not available")


def get_deglare() -> Optional["HeadlightDeglare"]:
    global _deglare
    if not DEGLARE_AVAILABLE:
        return None
    if _deglare is None:
        _deglare = HeadlightDeglare()
    return _deglare


# --- Perspective Fix (แก้ป้ายเอียง post-crop) ---
try:
    from .rtsp.perspective import Perspective
    _perspective_fixer: Optional["Perspective"] = None
    PERSPECTIVE_FIX_AVAILABLE = True
except ImportError:
    PERSPECTIVE_FIX_AVAILABLE = False
    _perspective_fixer = None


def get_perspective_fixer() -> Optional["Perspective"]:
    global _perspective_fixer
    if not PERSPECTIVE_FIX_AVAILABLE:
        return None
    if _perspective_fixer is None:
        _perspective_fixer = Perspective()
    return _perspective_fixer


from .inference.ocr import PlateOCR  # ใช้ OCR / parser ที่คุณมีอยู่แล้ว
from .inference.master_lookup import assist_with_master

log = logging.getLogger(__name__)


# ----------------------------
# Env
# ----------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage"))
MASTER_CONF_THRESHOLD = float(os.getenv("MASTER_CONF_THRESHOLD", "0.95"))
FEEDBACK_EXPORT_LIMIT = int(os.getenv("FEEDBACK_EXPORT_LIMIT", "200"))
TRAINING_DIR = Path(os.getenv("TRAINING_DIR", str(STORAGE_DIR / "training")))

# RTSP defaults
DEFAULT_RTSP_FPS = float(os.getenv("RTSP_FPS", "2.0"))
DEFAULT_RECONNECT_SEC = float(os.getenv("RTSP_RECONNECT_SEC", "2.0"))

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
    s = re.sub(r"[\s\-\.]", "", s)  # remove space/dash/dot
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
        # 1) DETECT + CROP (with optional deglare)
        # =============================================
        det = None
        crop_path = None

        deglare = get_deglare()
        if deglare:
            try:
                frame = cv2.imread(str(img_path))
                if frame is not None:
                    processed, original = deglare.process_for_detection(frame)

                    if original is not None:
                        # Deglare changed the image — try processed first
                        deglared_path = str(img_path) + ".deglared.jpg"
                        cv2.imwrite(deglared_path, processed)
                        try:
                            det = detector.detect_and_crop(deglared_path)
                            crop_path = det.crop_path
                            log.info("✅ Deglare helped: plate detected after preprocessing")
                        except RuntimeError:
                            try:
                                det = detector.detect_and_crop(str(img_path))
                                crop_path = det.crop_path
                            except RuntimeError:
                                pass
                        finally:
                            try:
                                Path(deglared_path).unlink(missing_ok=True)
                            except Exception:
                                pass
                    else:
                        det = detector.detect_and_crop(str(img_path))
                        crop_path = det.crop_path
            except RuntimeError:
                pass
            except Exception as e:
                log.warning("Deglare preprocessing error: %s", e)

        # Fallback: detect without deglare
        if det is None:
            det = detector.detect_and_crop(str(img_path))
            crop_path = det.crop_path

        # =============================================
        # 2) PERSPECTIVE FIX (post-crop, pre-OCR)
        # =============================================
        pfixer = get_perspective_fixer()
        if pfixer is not None:
            try:
                crop_img = cv2.imread(crop_path)
                if crop_img is not None:
                    fixed_img = pfixer.fix(crop_img)
                    cv2.imwrite(crop_path, fixed_img)
            except Exception as pe:
                log.warning("Perspective fix error (using original crop): %s", pe)

        # =============================================
        # 3) OCR
        # =============================================
        o = ocr.read_plate(crop_path, debug_dir=STORAGE_DIR / "debug", debug_id=str(capture_id))
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
        # 4) INSERT detections
        # =============================================
        sql_ins_det = text("""
            INSERT INTO detections (
                capture_id,
                crop_path,
                det_conf,
                bbox
            )
            VALUES (
                :capture_id,
                :crop_path,
                :det_conf,
                :bbox
            )
            RETURNING id
        """)

        detection_id = db.execute(sql_ins_det, {
            "capture_id": int(capture_id),
            "crop_path": str(crop_path),
            "det_conf": float(det.det_conf),
            "bbox": json.dumps(det.bbox or {}, ensure_ascii=False),
        }).scalar_one()

        # =============================================
        # 5) INSERT plate_reads
        # =============================================
        sql_ins_read = text("""
            INSERT INTO plate_reads (
                detection_id,
                plate_text,
                plate_text_norm,
                province,
                confidence,
                status,
                created_at
            )
            VALUES (
                :detection_id,
                :plate_text,
                :plate_text_norm,
                :province,
                :confidence,
                :status,
                :created_at
            )
            RETURNING id
        """)

        read_id = db.execute(sql_ins_read, {
            "detection_id": int(detection_id),
            "plate_text": (plate_text[:32] if plate_text else ""),
            "plate_text_norm": (plate_text_norm[:32] if plate_text_norm else ""),
            "province": (province[:64] if province else ""),
            "confidence": conf,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc),
        }).scalar_one()

        db.commit()

        # =============================================
        # 6) master logic
        # =============================================
        if conf >= MASTER_CONF_THRESHOLD and plate_text_norm:
            sql_upsert_master = text("""
                INSERT INTO master_plates (
                    plate_text_norm,
                    display_text,
                    province,
                    confidence,
                    last_seen,
                    count_seen,
                    editable
                )
                VALUES (
                    :plate_text_norm,
                    :display_text,
                    :province,
                    :confidence,
                    :last_seen,
                    :count_seen,
                    :editable
                )
                ON CONFLICT (plate_text_norm)
                DO UPDATE SET
                    display_text = CASE
                        WHEN master_plates.display_text = '' AND EXCLUDED.display_text <> '' THEN EXCLUDED.display_text
                        ELSE master_plates.display_text
                    END,
                    province = CASE
                        WHEN EXCLUDED.province <> '' THEN EXCLUDED.province
                        ELSE master_plates.province
                    END,
                    confidence = GREATEST(master_plates.confidence, EXCLUDED.confidence),
                    last_seen = EXCLUDED.last_seen,
                    count_seen = master_plates.count_seen + 1
            """)
            db.execute(sql_upsert_master, {
                "plate_text_norm": plate_text_norm,
                "display_text": (plate_text[:32] if plate_text else plate_text_norm),
                "province": province,
                "confidence": conf,
                "last_seen": now_utc(),
                "count_seen": 1,
                "editable": True,
            })
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
        return {"ok": False, "error": str(e), "capture_id": capture_id, "image_path": image_path}
    finally:
        db.close()


@celery_app.task(name="tasks.export_feedback_samples")
def export_feedback_samples(limit: int = FEEDBACK_EXPORT_LIMIT):
    """
    Export MLPR feedback samples into a training manifest.
    """
    images_dir = TRAINING_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = TRAINING_DIR / "manifest.jsonl"

    db = SessionLocal()
    try:
        sql_fetch = text("""
            SELECT id, crop_path, corrected_text, corrected_province
            FROM feedback_samples
            WHERE used_in_train = false
            ORDER BY created_at ASC
            LIMIT :limit
        """)
        rows = db.execute(sql_fetch, {"limit": int(limit)}).mappings().all()
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
                record = {
                    "image": str(dst),
                    "plate_text": row["corrected_text"],
                    "province": row["corrected_province"],
                    "source": "MLPR",
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        sql_mark = text("""
            UPDATE feedback_samples
            SET used_in_train = true
            WHERE id = ANY(:ids)
        """)
        db.execute(sql_mark, {"ids": [int(r["id"]) for r in rows]})
        db.commit()
        return {"ok": True, "exported": len(rows), "manifest": str(manifest_path)}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


# ----------------------------
# RTSP ingest task
# ----------------------------
@celery_app.task(name="tasks.rtsp_ingest")
def rtsp_ingest(camera_id: str, rtsp_url: str, fps: float = DEFAULT_RTSP_FPS, reconnect_sec: float = DEFAULT_RECONNECT_SEC):
    """
    Long-running RTSP ingest task.
    """
    fps = float(fps or DEFAULT_RTSP_FPS)
    reconnect_sec = float(reconnect_sec or DEFAULT_RECONNECT_SEC)
    interval = 1.0 / max(fps, 0.1)

    cap = None
    last_ts = 0.0

    while True:
        if should_stop(camera_id):
            if cap is not None:
                cap.release()
            return {"ok": True, "stopped": True, "camera_id": camera_id}

        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                time.sleep(reconnect_sec)
                continue

        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            cap = None
            time.sleep(reconnect_sec)
            continue

        now = time.time()
        if (now - last_ts) < interval:
            continue
        last_ts = now

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        out_path = STORAGE_DIR / "original" / f"rtsp_{camera_id}_{ts}.jpg"
        cv2.imwrite(str(out_path), frame)

        db = SessionLocal()
        try:
            digest = sha256_file(out_path)
            sql_ins_cap = text("""
                INSERT INTO captures (source, camera_id, captured_at, original_path, sha256)
                VALUES (:source, :camera_id, :captured_at, :original_path, :sha256)
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
            process_capture.delay(int(cap_id), str(out_path))
        except Exception:
            db.rollback()
        finally:
            db.close()