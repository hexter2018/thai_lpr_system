#!/usr/bin/env python3
"""
RTSP Frame Producer for Thai ALPR System (Enhanced)

Features:
- RTSP stream reading with auto-reconnect
- Motion detection filter
- Quality scoring with day/night adaptive thresholds
- Night preprocessing (optional) (CLAHE/denoise/sharpen)
- Frame deduplication
- BEST-SHOT: 1 car (1 plate) = 1 best image
- Celery task enqueue (tasks.process_capture)
- Track statistics in Redis
"""

import argparse
import hashlib
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import cv2
import numpy as np
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Base filters
from alpr_worker.rtsp.quality_filter import MotionDetector, QualityScorer, FrameDeduplicator
from alpr_worker.rtsp.config import RTSPConfig
from alpr_worker.celery_app import celery_app

# Inference (for best-shot keying + scoring)
from alpr_worker.inference.detector import PlateDetector
from alpr_worker.inference.ocr import PlateOCR
from alpr_worker.rtsp.best_shot import BestShotSelector, norm_plate_text

# Optional night modules
try:
    # NOTE: ใน repo บางเวอร์ชันอาจไม่มี EnhancedQualityFilter
    # เราจะใช้ scorer + ตรวจ night ด้วย brightness แทน (ทำให้รันได้แน่นอน)
    from alpr_worker.rtsp.quality_filter_v2 import EnhancedQualityScorer, AdaptiveMotionDetector
    V2_AVAILABLE = True
except Exception:
    EnhancedQualityScorer = None  # type: ignore
    AdaptiveMotionDetector = None  # type: ignore
    V2_AVAILABLE = False

try:
    from alpr_worker.rtsp.preprocessing import ImagePreprocessor
    PREPROCESS_AVAILABLE = True
except Exception:
    ImagePreprocessor = None  # type: ignore
    PREPROCESS_AVAILABLE = False

log = logging.getLogger(__name__)

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Bangkok


class RTSPFrameProducer:
    """
    RTSP Frame Producer with:
    - auto reconnect
    - filters: motion, quality, dedup
    - optional night preprocess
    - best-shot: 1 plate = 1 best image
    """

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        config: Optional[RTSPConfig] = None,
        enable_night_enhancement: bool = True,
        enable_preprocessing: bool = False,
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.config = config or RTSPConfig.from_env()

        # Night enhancement flags (soft)
        self.enable_night_enhancement = bool(enable_night_enhancement and V2_AVAILABLE)
        self.enable_preprocessing = bool(enable_preprocessing and PREPROCESS_AVAILABLE and self.enable_night_enhancement)

        # Day/Night detection threshold (brightness mean)
        self.night_brightness_level = float(os.getenv("NIGHT_BRIGHTNESS_LEVEL", "80.0"))
        # Adaptive min score at night (default 0.85 * day)
        self.min_quality_score_night = float(
            os.getenv("MIN_QUALITY_SCORE_NIGHT", str(float(self.config.min_quality_score) * 0.85))
        )

        # Database
        self.engine = create_engine(self.config.database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Redis
        self.redis = Redis.from_url(self.config.redis_url)

        # Storage
        self.storage_dir = Path(self.config.storage_dir)
        self.rtsp_dir = self.storage_dir / "rtsp" / camera_id
        self.rtsp_dir.mkdir(parents=True, exist_ok=True)

        # Debug dir (for bbox overlay)
        self.debug_dir = self.storage_dir / "debug"
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        # Setup filters
        self._setup_filters()

        # -------- Best-shot (1 car = 1 best image) --------
        self.enable_bestshot = os.getenv("RTSP_ENABLE_BESTSHOT", "true").lower() == "true"
        self.cooldown_sec = int(os.getenv("RTSP_BESTSHOT_COOLDOWN_SEC", "8"))
        self.draw_bbox_debug = os.getenv("RTSP_DRAW_BBOX_DEBUG", "false").lower() == "true"

        self.selector: Optional[BestShotSelector] = BestShotSelector() if self.enable_bestshot else None
        self.detector: Optional[PlateDetector] = None
        self.ocr: Optional[PlateOCR] = None

        if self.enable_bestshot:
            try:
                self.detector = PlateDetector()
                self.ocr = PlateOCR()
                log.info("✅ Best-shot enabled: detector+ocr initialized")
            except Exception as e:
                log.warning(f"⚠️ Best-shot disabled (cannot init detector/ocr): {e}")
                self.enable_bestshot = False
                self.selector = None
                self.detector = None
                self.ocr = None

        # Stats
        self.stats: Dict[str, Any] = {
            "frames_read": 0,
            "frames_dropped_motion": 0,
            "frames_dropped_quality": 0,
            "frames_dropped_duplicate": 0,
            "frames_preprocessed": 0,
            "frames_enqueued": 0,
            "night_mode_active": False,
            "last_update": None,
        }

        # State
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.last_frame_time = 0.0

        # Signals
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        log.info(f"RTSP Producer initialized for {camera_id}")
        log.info(f"Night enhancement: {self.enable_night_enhancement}")
        log.info(f"Preprocessing: {self.enable_preprocessing}")
        log.info(f"Best-shot: {self.enable_bestshot}")

    # ----------------------------
    # Filters
    # ----------------------------
    def _setup_filters(self):
        # Motion detector
        if self.config.enable_motion_filter:
            if self.enable_night_enhancement and AdaptiveMotionDetector is not None:
                # v2 motion detector (adaptive)
                self.motion_detector = AdaptiveMotionDetector(
                    day_threshold=float(self.config.motion_threshold),
                    night_threshold=float(self.config.motion_threshold) * 1.6,
                    night_brightness_level=self.night_brightness_level,
                )
                log.info("Using AdaptiveMotionDetector (day/night)")
            else:
                self.motion_detector = MotionDetector(threshold=self.config.motion_threshold)
                log.info("Using MotionDetector")
        else:
            self.motion_detector = None

        # Quality scorer
        if self.config.enable_quality_filter:
            if self.enable_night_enhancement and EnhancedQualityScorer is not None:
                # v2 scorer (glare/contrast aware)
                self.quality_scorer = EnhancedQualityScorer(min_score=float(self.config.min_quality_score))
                log.info("Using EnhancedQualityScorer (v2)")
            else:
                self.quality_scorer = QualityScorer(min_score=float(self.config.min_quality_score))
                log.info("Using QualityScorer")
        else:
            self.quality_scorer = None

        # Preprocessor (optional)
        if self.enable_preprocessing and ImagePreprocessor is not None:
            self.preprocessor = ImagePreprocessor()
            log.info("Image preprocessing enabled")
        else:
            self.preprocessor = None

        # Deduplicator
        if self.config.enable_dedup:
            self.deduplicator = FrameDeduplicator(
                cache_size=self.config.dedup_cache_size,
                threshold=self.config.dedup_threshold,
            )
        else:
            self.deduplicator = None

    # ----------------------------
    # Signals / Redis stats
    # ----------------------------
    def _signal_handler(self, signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _stop_key(self) -> str:
        return f"rtsp:stop:{self.camera_id}"

    def _stats_key(self) -> str:
        return f"rtsp:stats:{self.camera_id}"

    def should_stop(self) -> bool:
        try:
            return self.redis.get(self._stop_key()) == b"1"
        except Exception as e:
            log.warning(f"Failed to check stop flag: {e}")
            return False

    def _update_stats(self):
        try:
            self.stats["last_update"] = datetime.now(LOCAL_TZ).isoformat()
            self.redis.hset(self._stats_key(), mapping={k: str(v) for k, v in self.stats.items()})
        except Exception as e:
            log.warning(f"Failed to update stats: {e}")

    # ----------------------------
    # Stream / IO
    # ----------------------------
    def _connect_stream(self) -> bool:
        if self.cap is not None:
            self.cap.release()

        log.info(f"Connecting to RTSP stream: {self.camera_id}")
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

        if not self.cap.isOpened():
            log.error("Failed to open RTSP stream")
            return False

        log.info("RTSP stream connected")
        return True

    def _save_frame(self, frame: np.ndarray) -> str:
        timestamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = self.rtsp_dir / filename
        cv2.imwrite(str(filepath), frame)
        return str(filepath)

    def _sha256_file(self, filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _insert_capture(self, image_path: str) -> int:
        db = self.Session()
        try:
            sha256 = self._sha256_file(image_path)

            sql = text(
                """
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
                """
            )

            result = db.execute(
                sql,
                {
                    "source": "RTSP",
                    "camera_id": self.camera_id,
                    "captured_at": datetime.now(timezone.utc),
                    "original_path": image_path,
                    "sha256": sha256,
                },
            )

            capture_id = result.scalar_one()
            db.commit()
            return int(capture_id)
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def _enqueue_processing(self, capture_id: int, image_path: str):
        celery_app.send_task(
            "tasks.process_capture",
            args=[capture_id, image_path],
            queue="default",
        )

    # ----------------------------
    # Best-shot helpers
    # ----------------------------
    def _cooldown_key(self, plate_norm: str) -> str:
        return f"rtsp:cooldown:{self.camera_id}:{plate_norm}"

    def _finalize_best(self, fin: dict):
        """
        fin: {"tmp_path","plate_norm","bbox","score","ocr_conf",...}
        """
        tmp_path = fin.get("tmp_path")
        plate_norm = fin.get("plate_norm", "")
        if not tmp_path or not plate_norm:
            return

        # cooldown กันยิงซ้ำ
        try:
            self.redis.setex(self._cooldown_key(plate_norm), self.cooldown_sec, "1")
        except Exception as e:
            log.warning(f"Cooldown set failed: {e}")

        # (optional) debug bbox overlay
        if self.draw_bbox_debug and fin.get("bbox"):
            try:
                bgr = cv2.imread(str(tmp_path))
                if bgr is not None:
                    x1, y1, x2, y2 = fin["bbox"]
                    cv2.rectangle(bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    dbg = self.debug_dir / f"rtsp_bbox_{self.camera_id}_{plate_norm}_{int(time.time())}.jpg"
                    cv2.imwrite(str(dbg), bgr)
            except Exception:
                pass

        # insert capture + enqueue (1 คัน = 1 รูป)
        try:
            capture_id = self._insert_capture(tmp_path)
            self._enqueue_processing(capture_id, tmp_path)
            self.stats["frames_enqueued"] += 1
            log.info(
                f"✅ FINALIZE best-shot camera={self.camera_id} plate={plate_norm} "
                f"score={float(fin.get('score', 0.0)):.3f} conf={float(fin.get('ocr_conf', 0.0)):.2f}"
            )
        except Exception as e:
            log.error(f"Finalize failed: {e}")

    # ----------------------------
    # Frame processing
    # ----------------------------
    def _is_night(self, frame_bgr: np.ndarray) -> bool:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) < self.night_brightness_level

    def _process_frame(self, frame: np.ndarray) -> Tuple[bool, Optional[np.ndarray], Dict[str, Any]]:
        """
        Returns:
            should_process, enhanced_frame, metadata
        """
        metadata: Dict[str, Any] = {
            "quality_score": 0.0,
            "is_night": False,
            "preprocessed": False,
        }

        # Motion filter
        if self.motion_detector:
            if not self.motion_detector.has_motion(frame):
                self.stats["frames_dropped_motion"] += 1
                return False, None, metadata

        # Night detection (simple & stable)
        is_night = self._is_night(frame)
        metadata["is_night"] = is_night
        self.stats["night_mode_active"] = is_night

        # Quality filter (adaptive threshold day/night)
        if self.quality_scorer:
            score = float(self.quality_scorer.score(frame))
            metadata["quality_score"] = score

            min_req = float(self.min_quality_score_night) if is_night else float(self.config.min_quality_score)
            if score < min_req:
                self.stats["frames_dropped_quality"] += 1
                return False, None, metadata

        # Dedup filter
        if self.deduplicator:
            if self.deduplicator.is_duplicate(frame):
                self.stats["frames_dropped_duplicate"] += 1
                return False, None, metadata

        # Preprocess (only night)
        enhanced_frame = None
        if self.preprocessor and is_night:
            try:
                enhanced_frame = self.preprocessor.enhance(frame)
                metadata["preprocessed"] = True
                self.stats["frames_preprocessed"] += 1
            except Exception as e:
                log.warning(f"Preprocessing failed: {e}")
                enhanced_frame = None

        return True, enhanced_frame, metadata

    # ----------------------------
    # Main loop
    # ----------------------------
    def run(self):
        self.running = True
        frame_interval = 1.0 / max(float(self.config.target_fps), 0.1)

        log.info(f"Starting RTSP producer for {self.camera_id}")
        log.info(f"Target FPS: {self.config.target_fps}")
        log.info(
            f"Filters: motion={self.config.enable_motion_filter} "
            f"quality={self.config.enable_quality_filter} "
            f"dedup={self.config.enable_dedup} "
            f"preprocessing={self.enable_preprocessing} "
            f"bestshot={self.enable_bestshot}"
        )

        while self.running:
            if self.should_stop():
                log.info("Stop flag detected, shutting down...")
                break

            if self.cap is None or not self.cap.isOpened():
                if not self._connect_stream():
                    time.sleep(float(self.config.reconnect_sec))
                    continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                log.warning("Failed to read frame, reconnecting...")
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(float(self.config.reconnect_sec))
                continue

            self.stats["frames_read"] += 1

            # FPS throttling
            now = time.time()
            if (now - self.last_frame_time) < frame_interval:
                continue
            self.last_frame_time = now

            should_process, enhanced_frame, metadata = self._process_frame(frame)

            # ถ้าไม่ผ่าน filter -> ยังต้อง flush gap ของ best-shot (กันคันสุดท้ายหาย)
            if not should_process:
                if self.selector:
                    gap_fin = self.selector.flush_if_gap(time.time())
                    if gap_fin:
                        self._finalize_best(gap_fin)
                continue

            frame_to_use = enhanced_frame if enhanced_frame is not None else frame

            # Fallback: best-shot ไม่พร้อม -> ส่งทุกเฟรม (กันระบบล่ม)
            if not (self.enable_bestshot and self.selector and self.detector and self.ocr):
                try:
                    image_path = self._save_frame(frame_to_use)
                    capture_id = self._insert_capture(image_path)
                    self._enqueue_processing(capture_id, image_path)
                    self.stats["frames_enqueued"] += 1
                except Exception as e:
                    log.error(f"Failed to process frame: {e}")
                continue

            # -------- Best-shot mode (1 car = 1 best image) --------
            tmp_path = None
            try:
                # 1) save candidate
                tmp_path = self._save_frame(frame_to_use)

                # 2) detect + crop plate
                det = self.detector.detect_and_crop(tmp_path)
                crop_path = det.crop_path
                bbox = det.bbox.get("xyxy", None)
                det_conf = float(det.det_conf or 0.0)

                # 3) OCR
                o = self.ocr.read_plate(
                    crop_path,
                    debug_dir=self.debug_dir,
                    debug_id=f"rtsp_{self.camera_id}",
                )
                plate_norm = norm_plate_text((o.plate_text or ""))
                ocr_conf = float(o.confidence or 0.0)

                # ไม่ได้ป้าย -> ทิ้ง
                if not plate_norm:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    continue

                # cooldown -> ignore duplicates
                if self.redis.get(self._cooldown_key(plate_norm)) == b"1":
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    continue

                # 4) score candidate (plate ROI metrics)
                plate_bgr = cv2.imread(str(crop_path))
                if plate_bgr is None:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    continue

                h, w = frame_to_use.shape[:2]
                plate_area_ratio = 0.0
                if bbox:
                    x1, y1, x2, y2 = bbox
                    plate_area_ratio = max(0.0, ((x2 - x1) * (y2 - y1)) / float(w * h + 1e-6))

                frame_q = float(metadata.get("quality_score") or 0.0)
                score = float(self.selector.score(ocr_conf, det_conf, plate_bgr, frame_q, plate_area_ratio))
                fast = bool(ocr_conf >= float(self.selector.fast_conf))

                prev_best_path = self.selector.best.get("tmp_path") if self.selector.best else None

                cand = {
                    "tmp_path": tmp_path,
                    "plate_norm": plate_norm,
                    "bbox": bbox,
                    "ocr_conf": ocr_conf,
                    "det_conf": det_conf,
                    "score": score,
                    "fast": fast,
                }

                fin = self.selector.update(time.time(), plate_norm, cand)

                # ถ้าไม่ finalize -> ลบไฟล์ที่แพ้ / ลบ best เก่าที่ถูกแทนที่
                if fin is None:
                    cur_best_path = self.selector.best.get("tmp_path") if self.selector.best else None

                    # candidate แพ้
                    if cur_best_path and cur_best_path != tmp_path:
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

                    # best ถูก replace
                    if prev_best_path and cur_best_path and prev_best_path != cur_best_path:
                        try:
                            os.remove(prev_best_path)
                        except Exception:
                            pass

                # finalize เมื่อครบ window/fast_conf/เปลี่ยนคัน
                if fin:
                    self._finalize_best(fin)

                # flush if gap (รถหาย)
                gap_fin = self.selector.flush_if_gap(time.time())
                if gap_fin:
                    self._finalize_best(gap_fin)

            except Exception as e:
                log.warning(f"Best-shot candidate failed: {e}")
                if tmp_path:
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                continue

            # update stats every 10 enqueued
            if self.stats["frames_enqueued"] % 10 == 0 and self.stats["frames_enqueued"] > 0:
                self._update_stats()

        # Cleanup
        self.stop()

    def stop(self):
        self.running = False

        # ถ้ามี best-shot ค้างอยู่ -> finalize ก่อนปิด (กันหาย)
        try:
            if self.selector and self.selector.best:
                self._finalize_best(self.selector.best)
                self.selector.reset()
        except Exception:
            pass

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        self._update_stats()
        log.info(f"Producer stopped. Stats: {self.stats}")


def main():
    parser = argparse.ArgumentParser(description="RTSP Frame Producer for Thai ALPR (Enhanced)")
    parser.add_argument("--camera-id", required=True, help="Camera ID")
    parser.add_argument("--rtsp-url", required=True, help="RTSP stream URL")
    parser.add_argument("--fps", type=float, default=2.0, help="Target FPS (default: 2.0)")
    parser.add_argument(
        "--enable-night-enhancement",
        action="store_true",
        default=True,
        help="Enable night-time enhancement (default: True)",
    )
    parser.add_argument("--disable-night-enhancement", action="store_true", help="Disable night-time enhancement")
    parser.add_argument("--enable-preprocessing", action="store_true", help="Enable preprocessing for night frames")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = RTSPConfig.from_env()
    config.target_fps = float(args.fps)

    enable_night = bool(args.enable_night_enhancement and not args.disable_night_enhancement)

    producer = RTSPFrameProducer(
        camera_id=args.camera_id,
        rtsp_url=args.rtsp_url,
        config=config,
        enable_night_enhancement=enable_night,
        enable_preprocessing=bool(args.enable_preprocessing),
    )

    try:
        producer.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error(f"Producer failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())