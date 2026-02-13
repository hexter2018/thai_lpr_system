#!/usr/bin/env python3
"""RTSP producer v2 with YOLO zone-triggered capture."""

import argparse
import hashlib
import logging
import os
import signal
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from alpr_worker.celery_app import celery_app
from alpr_worker.rtsp.best_shot import BestShotBuffer, FrameCandidate
from alpr_worker.rtsp.config import RTSPConfig
from alpr_worker.rtsp.preprocessing import ImagePreprocessor
from alpr_worker.rtsp.quality_filter import FrameDeduplicator, MotionDetector, QualityScorer
from alpr_worker.rtsp.quality_filter_v2 import EnhancedQualityScorer
from alpr_worker.rtsp.quality_gate import QualityGate
from alpr_worker.rtsp.roi_reader import ROIReader
from alpr_worker.rtsp.vehicle_detector import VehicleDetector, ZoneDetectionResult
from alpr_worker.rtsp.zone_trigger import CaptureZone, load_zones_from_env

log = logging.getLogger(__name__)
LOCAL_TZ = timezone(timedelta(hours=7))


class ZoneCooldown:
    def __init__(self, cooldown_sec: float = 3.0):
        self.cooldown_sec = cooldown_sec
        self._last_trigger: Dict[str, float] = defaultdict(float)

    def is_ready(self, zone_name: str, now: float) -> bool:
        return (now - self._last_trigger[zone_name]) >= self.cooldown_sec

    def mark(self, zone_name: str, now: float):
        self._last_trigger[zone_name] = now


class RTSPFrameProducerV2:
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
        self.enable_night_enhancement = enable_night_enhancement
        self.enable_preprocessing = enable_preprocessing

        self.engine = create_engine(self.config.database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)
        self.redis = Redis.from_url(self.config.redis_url)
        self.last_heartbeat = 0.0

        self.storage_dir = Path(self.config.storage_dir)
        self.rtsp_dir = self.storage_dir / "rtsp" / camera_id
        self.rtsp_dir.mkdir(parents=True, exist_ok=True)

        self._roi_reader = None
        try:
            self._roi_reader = ROIReader(redis_client=self.redis, camera_id=camera_id)
        except Exception:
            pass

        self._setup_filters()

        self.vehicle_detector = VehicleDetector()
        self.zones: List[CaptureZone] = load_zones_from_env()
        self.zone_cooldown = ZoneCooldown(float(os.getenv("VEHICLE_DETECTOR_COOLDOWN_SEC", "3.0")))

        self.quality_gate = QualityGate()
        self.best_shot_buffer = BestShotBuffer()

        self.stats: Dict[str, Any] = {
            "frames_read": 0,
            "frames_dropped_motion": 0,
            "frames_dropped_quality": 0,
            "frames_dropped_duplicate": 0,
            "frames_dropped_cooldown": 0,
            "frames_enqueued": 0,
            "yolo_detections_total": 0,
            "yolo_zone_triggers": 0,
            "yolo_inference_ms_avg": 0.0,
            "night_mode_active": False,
            "last_update": None,
            "zone_stats": {z.name: {"triggers": 0, "last_trigger": ""} for z in self.zones},
        }

        self._latest_annotated: Optional[np.ndarray] = None
        self._latest_raw: Optional[np.ndarray] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.last_frame_time = 0.0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_filters(self):
        self.motion_detector = MotionDetector(threshold=self.config.motion_threshold) if self.config.enable_motion_filter else None
        if self.enable_night_enhancement:
            self.quality_filter = EnhancedQualityScorer()
        elif self.config.enable_quality_filter:
            self.quality_filter = QualityScorer(min_score=self.config.min_quality_score)
        else:
            self.quality_filter = None
        self.preprocessor = ImagePreprocessor() if self.enable_preprocessing else None
        self.deduplicator = FrameDeduplicator(cache_size=self.config.dedup_cache_size, threshold=self.config.dedup_threshold) if self.config.enable_dedup else None

    def _signal_handler(self, signum, frame):
        log.info("Signal %d received, stopping...", signum)
        self.stop()

    def should_stop(self) -> bool:
        try:
            return self.redis.get(f"rtsp:stop:{self.camera_id}") == b"1"
        except Exception:
            return False

    def _send_heartbeat(self):
        now = time.time()
        if now - self.last_heartbeat >= 10:
            try:
                self.redis.setex(f"alpr:camera_heartbeat:{self.camera_id}", 30, str(now))
                self.last_heartbeat = now
            except Exception:
                pass

    def _update_stats(self):
        try:
            self.stats["last_update"] = datetime.now(LOCAL_TZ).isoformat()
            flat = {k: (str(v) if k != "zone_stats" else __import__("json").dumps(v)) for k, v in self.stats.items()}
            self.redis.hset(f"rtsp:stats:{self.camera_id}", mapping=flat)
            if self._latest_annotated is not None:
                ok, jpg = cv2.imencode(".jpg", self._latest_annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    self.redis.setex(f"alpr:preview:{self.camera_id}", 5, jpg.tobytes())
        except Exception:
            pass

    def _push_yolo_frame(self, annotated: np.ndarray):
        try:
            ok, jpg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                self.redis.setex(f"alpr:yolo_preview:{self.camera_id}", 3, jpg.tobytes())
        except Exception:
            pass

    def _connect_stream(self) -> bool:
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        return self.cap.isOpened()

    def _get_current_roi(self) -> dict:
        if self._roi_reader:
            try:
                return self._roi_reader.get_roi()
            except Exception:
                pass
        return {"x1": float(os.getenv("RTSP_ROI_X1", "0.0")), "y1": float(os.getenv("RTSP_ROI_Y1", "0.0")), "x2": float(os.getenv("RTSP_ROI_X2", "1.0")), "y2": float(os.getenv("RTSP_ROI_Y2", "1.0"))}

    def _apply_roi(self, frame: np.ndarray) -> np.ndarray:
        if os.getenv("RTSP_ROI_ENABLED", "false").lower() != "true":
            return frame
        roi = self._get_current_roi()
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = int(roi["x1"] * w), int(roi["y1"] * h), int(roi["x2"] * w), int(roi["y2"] * h)
        return frame[max(0, y1):max(y1 + 1, min(h, y2)), max(0, x1):max(x1 + 1, min(w, x2))]

    def _quality_pass(self, frame: np.ndarray) -> tuple[bool, float]:
        if self.motion_detector and not self.motion_detector.has_motion(frame):
            self.stats["frames_dropped_motion"] += 1
            return False, 0.0
        score = 0.0
        if self.quality_filter:
            if hasattr(self.quality_filter, "evaluate"):
                result = self.quality_filter.evaluate(frame)
                score = result.quality_score
                self.stats["night_mode_active"] = result.is_night
                if not result.passed:
                    self.stats["frames_dropped_quality"] += 1
                    return False, score
            else:
                score = self.quality_filter.score(frame)
        if self.deduplicator and self.deduplicator.is_duplicate(frame):
            self.stats["frames_dropped_duplicate"] += 1
            return False, score
        return True, score

    def _save_frame(self, frame: np.ndarray, zone_name: str = "") -> str:
        ts = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{zone_name}" if zone_name else ""
        filepath = self.rtsp_dir / f"{ts}{suffix}_{uuid.uuid4().hex[:6]}.jpg"
        cv2.imwrite(str(filepath), frame)
        return str(filepath)

    def _sha256(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _insert_capture(self, image_path: str) -> int:
        db = self.Session()
        try:
            r = db.execute(text("INSERT INTO captures (source, camera_id, captured_at, original_path, sha256) VALUES (:source,:camera_id,:captured_at,:original_path,:sha256) RETURNING id"), {
                "source": "RTSP",
                "camera_id": self.camera_id,
                "captured_at": datetime.now(timezone.utc),
                "original_path": image_path,
                "sha256": self._sha256(image_path),
            })
            capture_id = r.scalar_one()
            db.commit()
            return capture_id
        finally:
            db.close()

    def _enqueue(self, capture_id: int, image_path: str):
        celery_app.send_task("tasks.process_capture", args=[capture_id, image_path], queue="default")

    def run(self):
        self.running = True
        frame_interval = 1.0 / self.config.target_fps
        while self.running:
            if self.should_stop():
                break
            if self.cap is None or not self.cap.isOpened():
                if not self._connect_stream():
                    time.sleep(self.config.reconnect_sec)
                    continue
            ret, raw_frame = self.cap.read()
            if not ret or raw_frame is None:
                self.cap.release()
                self.cap = None
                time.sleep(self.config.reconnect_sec)
                continue

            self.stats["frames_read"] += 1
            self._send_heartbeat()
            now = time.time()
            if (now - self.last_frame_time) < frame_interval:
                continue
            self.last_frame_time = now

            frame = self._apply_roi(raw_frame)
            self._latest_raw = frame
            passed, _ = self._quality_pass(frame)
            if not passed:
                continue

            if self.vehicle_detector.is_ready and self.zones:
                det_result: ZoneDetectionResult = self.vehicle_detector.detect_in_zones(frame, self.zones, draw=True)
                self.stats["yolo_inference_ms_avg"] = 0.9 * self.stats["yolo_inference_ms_avg"] + 0.1 * det_result.inference_ms
                self.stats["yolo_detections_total"] += len(det_result.detections)
                if det_result.annotated_frame is not None:
                    self._latest_annotated = det_result.annotated_frame
                    self._push_yolo_frame(det_result.annotated_frame)

                for zone_name in det_result.triggered_zones:
                    if not self.zone_cooldown.is_ready(zone_name, now):
                        self.stats["frames_dropped_cooldown"] += 1
                        continue
                    gate = self.quality_gate.check(frame)
                    if not gate.passed:
                        continue
                    self.zone_cooldown.mark(zone_name, now)
                    self.stats["yolo_zone_triggers"] += 1
                    self.stats["zone_stats"][zone_name]["triggers"] += 1
                    self.stats["zone_stats"][zone_name]["last_trigger"] = datetime.now(LOCAL_TZ).isoformat()
                    save_frame = self.preprocessor.enhance(frame) if self.preprocessor and self.stats.get("night_mode_active") else frame
                    img_path = self._save_frame(save_frame, zone_name=zone_name)
                    capture_id = self._insert_capture(img_path)
                    self._enqueue(capture_id, img_path)
                    self.stats["frames_enqueued"] += 1
            else:
                gate = self.quality_gate.check(frame)
                if not gate.passed:
                    continue
                cand = FrameCandidate(image_path=self._save_frame(frame), quality_score=gate.score, timestamp=now, metadata={"quality_score": gate.score})
                selected = self.best_shot_buffer.add(cand)
                if selected:
                    self._enqueue_selected(selected)

            if self.stats["frames_read"] % 10 == 0:
                self._update_stats()
        self.stop()

    def _enqueue_selected(self, selected: FrameCandidate):
        capture_id = self._insert_capture(selected.image_path)
        self._enqueue(capture_id, selected.image_path)
        self.stats["frames_enqueued"] += 1

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        self._update_stats()


def main():
    parser = argparse.ArgumentParser(description="RTSP Frame Producer V2 — YOLO Vehicle Detection + Zone Capture")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--rtsp-url", required=True)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--disable-night-enhancement", action="store_true")
    parser.add_argument("--enable-preprocessing", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s")
    config = RTSPConfig.from_env()
    config.target_fps = args.fps

    producer = RTSPFrameProducerV2(
        camera_id=args.camera_id,
        rtsp_url=args.rtsp_url,
        config=config,
        enable_night_enhancement=not args.disable_night_enhancement,
        enable_preprocessing=args.enable_preprocessing,
    )
    try:
        producer.run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log.error("Producer error: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
