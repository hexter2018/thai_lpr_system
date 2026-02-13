#!/usr/bin/env python3
"""
RTSP Frame Producer for Thai ALPR System (Enhanced with Vehicle Tracking)

Features:
- RTSP stream reading with auto-reconnect
- Motion detection filter
- Quality scoring with day/night adaptive thresholds
- Enhanced quality filter v2 (glare detection, contrast analysis)
- Image preprocessing (CLAHE, denoising, sharpening)
- Frame deduplication
- **Vehicle Tracking** — Track vehicles to avoid duplicate captures
- Celery task enqueue

Vehicle Tracking:
- Assigns unique tracking ID to each vehicle
- Tracks vehicle state across frames
- Ensures each vehicle is captured only ONCE
- Configurable cooldown per vehicle
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
from typing import Optional, Dict, Any

import cv2
import numpy as np
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import existing modules
from alpr_worker.rtsp.quality_filter import MotionDetector, QualityScorer, FrameDeduplicator
from alpr_worker.rtsp.best_shot import BestShotBuffer, FrameCandidate
from alpr_worker.rtsp.quality_gate import QualityGate
from alpr_worker.rtsp.config import RTSPConfig
from alpr_worker.rtsp.line_trigger import VirtualLineTrigger, LineTriggerConfig
from alpr_worker.celery_app import celery_app

# ─── ROI Reader (feature flag) ───
try:
    from alpr_worker.rtsp.roi_reader import ROIReader
    ROI_READER_AVAILABLE = True
except ImportError:
    ROIReader = None
    ROI_READER_AVAILABLE = False

# ─── Zone Trigger (วิธี 3: กำหนดจุด capture แบบ polygon) ───
try:
    from alpr_worker.rtsp.zone_trigger import ZoneTrigger, load_zones_from_env
    ZONE_TRIGGER_AVAILABLE = True
except ImportError:
    ZoneTrigger = None
    load_zones_from_env = None
    ZONE_TRIGGER_AVAILABLE = False

# ─── Vehicle Tracker (prevent duplicate captures) ───
try:
    from alpr_worker.rtsp.vehicle_tracker import VehicleTracker, create_tracker_from_env
    VEHICLE_TRACKER_AVAILABLE = True
except ImportError:
    VehicleTracker = None
    create_tracker_from_env = None
    VEHICLE_TRACKER_AVAILABLE = False

# Import night enhancement modules (optional)
_NIGHT_ENHANCEMENT_IMPORT_ERRORS: Dict[str, str] = {}

try:
    from alpr_worker.rtsp.quality_filter_v2 import EnhancedQualityScorer
    ENHANCED_SCORER_AVAILABLE = True
except ImportError as exc:
    EnhancedQualityScorer = None
    ENHANCED_SCORER_AVAILABLE = False
    _NIGHT_ENHANCEMENT_IMPORT_ERRORS["quality_filter_v2"] = str(exc)

try:
    from alpr_worker.rtsp.preprocessing import ImagePreprocessor
    PREPROCESSOR_AVAILABLE = True
except ImportError as exc:
    ImagePreprocessor = None
    PREPROCESSOR_AVAILABLE = False
    _NIGHT_ENHANCEMENT_IMPORT_ERRORS["preprocessing"] = str(exc)

NIGHT_ENHANCEMENT_AVAILABLE = ENHANCED_SCORER_AVAILABLE or PREPROCESSOR_AVAILABLE

if _NIGHT_ENHANCEMENT_IMPORT_ERRORS:
    logging.warning(
        "Night enhancement modules unavailable: %s",
        ", ".join(
            f"{module} ({error})" for module, error in _NIGHT_ENHANCEMENT_IMPORT_ERRORS.items()
        ),
    )

log = logging.getLogger(__name__)

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Bangkok


class RTSPFrameProducer:
    """
    RTSP Frame Producer with Vehicle Tracking
    
    Features:
    - Read RTSP stream with auto-reconnect
    - Filter frames: motion detection, quality check, deduplication
    - **Track vehicles** to ensure single capture per vehicle
    - Night-time enhancement (optional)
    - Save frames and enqueue to existing process_capture task
    - Track statistics in Redis
    """
    
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        config: Optional[RTSPConfig] = None,
        enable_night_enhancement: bool = True,
        enable_preprocessing: bool = True,
        enable_tracking: bool = True,
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.config = config or RTSPConfig.from_env()
        
        # Night enhancement flags
        self.enable_night_enhancement = enable_night_enhancement and ENHANCED_SCORER_AVAILABLE
        self.enable_preprocessing = enable_preprocessing and PREPROCESSOR_AVAILABLE
        
        # Vehicle tracking flag
        self.enable_tracking = enable_tracking and VEHICLE_TRACKER_AVAILABLE
        
        # Database
        self.engine = create_engine(self.config.database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)
        
        # Redis
        self.redis = Redis.from_url(self.config.redis_url)
        self.last_heartbeat = 0
        
        # ROI Reader (Dashboard → Redis → ENV fallback)
        self._roi_reader = None
        if ROI_READER_AVAILABLE:
            try:
                self._roi_reader = ROIReader(
                    redis_client=self.redis,
                    camera_id=camera_id,
                )
                log.info("ROIReader: camera=%s source=%s", camera_id, self._roi_reader.get_source())
            except Exception as e:
                log.warning("ROIReader init failed (using ENV): %s", e)
                self._roi_reader = None
        
        # Storage
        self.storage_dir = Path(self.config.storage_dir)
        self.rtsp_dir = self.storage_dir / "rtsp" / camera_id
        self.rtsp_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup filters (with night enhancement if available)
        self._setup_filters()
        
        # ⭐ Vehicle Tracker
        self.vehicle_tracker: Optional[VehicleTracker] = None
        if self.enable_tracking:
            self.vehicle_tracker = create_tracker_from_env()
            if self.vehicle_tracker:
                log.info("✅ Vehicle tracking ENABLED (no duplicate captures)")
            else:
                log.warning("Vehicle tracking DISABLED (set VEHICLE_TRACKING_ENABLED=true)")
                self.enable_tracking = False
        
        # Stats
        self.stats = {
            "frames_read": 0,
            "frames_dropped_motion": 0,
            "frames_dropped_quality": 0,
            "frames_dropped_duplicate": 0,
            "frames_dropped_line": 0,
            "frames_dropped_tracking": 0,  # ⭐ NEW
            "frames_enhanced": 0,
            "frames_preprocessed": 0,
            "frames_enqueued": 0,
            "frames_buffered": 0,
            "frames_discarded_by_bestshot": 0,
            "frames_rejected_quality_gate": 0,
            "vehicles_tracked": 0,  # ⭐ NEW
            "vehicles_captured": 0,  # ⭐ NEW
            "night_mode_active": False,
            "last_update": None,
        }
        
        # Quality Gate + Best Shot Buffer
        self.quality_gate = QualityGate()
        self.best_shot_buffer = BestShotBuffer()
        
        # Optional virtual line trigger
        self.line_trigger = VirtualLineTrigger(LineTriggerConfig.from_env())

        # Optional zone trigger (วิธี 3)
        self.zone_trigger = None
        if ZONE_TRIGGER_AVAILABLE and load_zones_from_env is not None:
            try:
                zones = load_zones_from_env()
                if zones:
                    self.zone_trigger = ZoneTrigger(zones)
                    log.info(
                        "ZoneTrigger enabled: %d zones (%s)",
                        len(zones), [z.name for z in zones]
                    )
            except Exception as e:
                log.warning("ZoneTrigger init failed (disabled): %s", e)
            
        # State
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.last_frame_time = 0.0
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Log configuration
        log.info(f"RTSP Producer initialized for {camera_id}")
        log.info(f"Night enhancement: {self.enable_night_enhancement}")
        log.info(f"Preprocessing: {self.enable_preprocessing}")
        log.info(f"Vehicle tracking: {self.enable_tracking}")
        if self.line_trigger.enabled:
            cfg = self.line_trigger.config
            log.info(
                "Virtual line trigger enabled: (%.2f, %.2f)->(%.2f, %.2f), direction=%s, band=%spx",
                cfg.x1, cfg.y1, cfg.x2, cfg.y2, cfg.direction, cfg.band_px
            )        
    
    def _setup_filters(self):
        """Setup quality filters with optional night enhancement"""
        
        # Motion detector (standard)
        self.motion_detector = MotionDetector(
            threshold=self.config.motion_threshold
        ) if self.config.enable_motion_filter else None
        
        # Quality filter - choose version
        if self.enable_night_enhancement and EnhancedQualityScorer:
            # Use enhanced quality filter v2 with day/night detection
            self.quality_filter = EnhancedQualityScorer()
            log.info("Using EnhancedQualityFilter v2 (day/night adaptive)")
        elif self.config.enable_quality_filter:
            # Use standard quality scorer
            self.quality_filter = QualityScorer(
                min_score=self.config.min_quality_score
            )
            log.info("Using standard QualityScorer")
        else:
            self.quality_filter = None
        
        # Preprocessor (optional)
        if self.enable_preprocessing and ImagePreprocessor:
            self.preprocessor = ImagePreprocessor()
            log.info("Image preprocessing enabled")
        else:
            self.preprocessor = None
        
        # Deduplicator (standard)
        self.deduplicator = FrameDeduplicator(
            cache_size=self.config.dedup_cache_size,
            threshold=self.config.dedup_threshold
        ) if self.config.enable_dedup else None
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        log.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def _stop_key(self) -> str:
        """Redis key for stop flag"""
        return f"rtsp:stop:{self.camera_id}"
    
    def _stats_key(self) -> str:
        """Redis key for stats"""
        return f"rtsp:stats:{self.camera_id}"
    
    def _heartbeat_key(self) -> str:
        """Redis key for camera heartbeat (Dashboard status)"""
        return f"alpr:camera_heartbeat:{self.camera_id}"
    
    def _send_heartbeat(self):
        """Send heartbeat to Redis every 10 seconds (for Dashboard status)"""
        now = time.time()
        if now - self.last_heartbeat >= 10:
            try:
                self.redis.setex(self._heartbeat_key(), 30, str(now))
                self.last_heartbeat = now
                log.debug(f"[{self.camera_id}] Heartbeat sent")
            except Exception as e:
                log.warning(f"[{self.camera_id}] Heartbeat failed: {e}")
    
    def should_stop(self) -> bool:
        """Check if stop flag is set in Redis"""
        try:
            return self.redis.get(self._stop_key()) == b"1"
        except Exception as e:
            log.warning(f"Failed to check stop flag: {e}")
            return False
    
    def _update_stats(self):
        """Update stats in Redis"""
        try:
            self.stats["last_update"] = datetime.now(LOCAL_TZ).isoformat()
            self.redis.hset(
                self._stats_key(),
                mapping={k: str(v) for k, v in self.stats.items()}
            )
        except Exception as e:
            log.warning(f"Failed to update stats: {e}")
    
    def _connect_stream(self) -> bool:
        """Connect to RTSP stream"""
        if self.cap is not None:
            self.cap.release()
        
        log.info(f"Connecting to RTSP stream: {self.camera_id}")
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        
        if not self.cap.isOpened():
            log.error("Failed to open RTSP stream")
            return False
        
        # Reset tracking state on reconnect
        if self.vehicle_tracker:
            self.vehicle_tracker.reset()
        
        log.info("RTSP stream connected")
        return True
    
    def _save_frame(self, frame: np.ndarray, track_id: Optional[int] = None) -> str:
        """
        Save frame to disk and return path
        
        Args:
            frame: BGR image
            track_id: Vehicle tracking ID (optional, for filename)
        """
        timestamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S_%f")
        if track_id is not None:
            filename = f"{timestamp}_track{track_id:04d}_{uuid.uuid4().hex[:6]}.jpg"
        else:
            filename = f"{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        
        filepath = self.rtsp_dir / filename
        cv2.imwrite(str(filepath), frame)
        return str(filepath)
    
    def _sha256_file(self, filepath: str) -> str:
        """Calculate SHA256 hash of file"""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    
    def _insert_capture(self, image_path: str, track_id: Optional[int] = None) -> int:
        """
        Insert capture record into database
        
        Args:
            image_path: Path to saved frame
            track_id: Vehicle tracking ID (optional)
        
        Returns:
            capture_id
        """
        db = self.Session()
        try:
            sha256 = self._sha256_file(image_path)
            
            # ⭐ Add track_id to metadata if available
            metadata = {}
            if track_id is not None:
                metadata["track_id"] = track_id
            
            sql = text("""
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
            
            result = db.execute(sql, {
                "source": "RTSP",
                "camera_id": self.camera_id,
                "captured_at": datetime.now(timezone.utc),
                "original_path": image_path,
                "sha256": sha256,
            })
            
            capture_id = result.scalar_one()
            db.commit()
            return capture_id
            
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    
    def _enqueue_processing(self, capture_id: int, image_path: str):
        """
        Enqueue frame for processing using existing process_capture task
        """
        celery_app.send_task(
            "tasks.process_capture",
            args=[capture_id, image_path],
            queue="default",
        )
    
    def _get_current_roi(self) -> dict:
        """
        อ่าน ROI ปัจจุบัน — safe, never throws

        Priority:
          1. ROIReader (Redis ← Dashboard)
          2. ENV (docker-compose)
          3. Full frame
        """
        if self._roi_reader is not None:
            try:
                return self._roi_reader.get_roi()
            except Exception:
                pass
        # Fallback: ENV เดิม
        return {
            "x1": float(os.getenv("RTSP_ROI_X1", "0.0")),
            "y1": float(os.getenv("RTSP_ROI_Y1", "0.0")),
            "x2": float(os.getenv("RTSP_ROI_X2", "1.0")),
            "y2": float(os.getenv("RTSP_ROI_Y2", "1.0")),
        }

    def _process_frame(self, frame: np.ndarray) -> tuple[bool, Optional[np.ndarray], Dict[str, Any]]:
        """
        Process single frame through filters
        
        Returns:
            (should_process, enhanced_frame, metadata)
            - should_process: True if frame should be processed, False if dropped
            - enhanced_frame: Preprocessed frame (if preprocessing enabled), else None
            - metadata: Processing metadata (quality score, night mode, etc.)
        """
        metadata: Dict[str, Any] = {
            "quality_score": 0.0,
            "is_night": False,
            "enhanced": False,
            "preprocessed": False,
        }
        
        # Motion filter
        if self.motion_detector:
            if not self.motion_detector.has_motion(frame):
                self.stats["frames_dropped_motion"] += 1
                return False, None, metadata
        
        # Quality filter with night enhancement
        if self.quality_filter:
            if hasattr(self.quality_filter, 'evaluate'):
                # Enhanced quality filter v2
                result = self.quality_filter.evaluate(frame)
                metadata["quality_score"] = result.quality_score
                metadata["is_night"] = result.is_night
                self.stats["night_mode_active"] = result.is_night
                
                if not result.passed:
                    self.stats["frames_dropped_quality"] += 1
                    return False, None, metadata
                
                metadata["enhanced"] = True
                self.stats["frames_enhanced"] += 1
            else:
                # Standard quality scorer
                score = self.quality_filter.score(frame)
                metadata["quality_score"] = score
                
                if score < self.config.min_quality_score:
                    self.stats["frames_dropped_quality"] += 1
                    return False, None, metadata
        
        # Deduplication filter (before preprocessing to avoid duplicate processing)
        if self.deduplicator:
            if self.deduplicator.is_duplicate(frame):
                self.stats["frames_dropped_duplicate"] += 1
                return False, None, metadata
        
        # Image preprocessing (optional, only for night frames)
        enhanced_frame = None
        if self.preprocessor and metadata.get("is_night", False):
            try:
                enhanced_frame = self.preprocessor.enhance(frame)
                metadata["preprocessed"] = True
                self.stats["frames_preprocessed"] += 1
            except Exception as e:
                log.warning(f"Preprocessing failed: {e}")
                enhanced_frame = None
        
        return True, enhanced_frame, metadata
    
    def run(self):
        """Main loop with vehicle tracking"""
        self.running = True
        frame_interval = 1.0 / self.config.target_fps
        
        log.info(f"Starting RTSP producer for {self.camera_id}")
        log.info(f"Target FPS: {self.config.target_fps}")
        log.info(f"Filters: motion={self.config.enable_motion_filter} "
                f"quality={'enhanced_v2' if self.enable_night_enhancement else 'standard'} "
                f"dedup={self.config.enable_dedup} "
                f"preprocessing={self.enable_preprocessing} "
                f"tracking={self.enable_tracking}")
        
        while self.running:
            # Check stop flag
            if self.should_stop():
                log.info("Stop flag detected, shutting down...")
                break
            
            # Connect to stream
            if self.cap is None or not self.cap.isOpened():
                if not self._connect_stream():
                    time.sleep(self.config.reconnect_sec)
                    continue
            
            # Read frame
            ret, frame = self.cap.read()
            if not ret or frame is None:
                log.warning("Failed to read frame, reconnecting...")
                self.cap.release()
                self.cap = None
                time.sleep(self.config.reconnect_sec)
                continue
            
            self.stats["frames_read"] += 1

            # ─── Send heartbeat to Dashboard (every 10s) ───
            self._send_heartbeat()
            
            # FPS throttling
            now = time.time()
            if (now - self.last_frame_time) < frame_interval:
                continue
            self.last_frame_time = now
            
            # ─── ROI Crop (dynamic from Dashboard/Redis/ENV) ───
            roi_enabled = os.getenv("RTSP_ROI_ENABLED", "false").lower() == "true"
            if roi_enabled:
                roi = self._get_current_roi()
                h, w = frame.shape[:2]
                rx1 = max(0, min(int(roi["x1"] * w), w - 1))
                ry1 = max(0, min(int(roi["y1"] * h), h - 1))
                rx2 = max(rx1 + 1, min(int(roi["x2"] * w), w))
                ry2 = max(ry1 + 1, min(int(roi["y2"] * h), h))
                frame = frame[ry1:ry2, rx1:rx2]

            # ⭐ Vehicle Tracking — Update tracker
            ready_to_capture_tracks = []
            if self.vehicle_tracker:
                tracking_result = self.vehicle_tracker.update(frame, now)
                self.stats["vehicles_tracked"] = tracking_result.total_tracks
                ready_to_capture_tracks = tracking_result.ready_to_capture
                
                # Log new tracks
                if tracking_result.new_tracks:
                    for track in tracking_result.new_tracks:
                        log.info(f"🚗 New vehicle detected: Track ID {track.track_id}")
            
            # Line trigger check (if enabled)
            if self.line_trigger.enabled and not self.line_trigger.check(frame, now):
                self.stats["frames_dropped_line"] += 1
                continue

            # Zone Trigger check (วิธี 3 — ทำงานแทน line trigger ถ้า enabled)
            if self.zone_trigger is not None:
                zone_result = self.zone_trigger.check_full(frame, now)
                if not zone_result.triggered:
                    self.stats["frames_dropped_line"] += 1
                    continue
            
            # ⭐ Check if we should capture based on tracking
            if self.vehicle_tracker and ready_to_capture_tracks:
                # We have vehicles ready to capture
                # Pick the best one (largest area / most stable)
                best_track = max(ready_to_capture_tracks, key=lambda t: t.area * t.hits)
                
                # Check if already captured recently
                if self.vehicle_tracker.was_captured(best_track.track_id, now):
                    self.stats["frames_dropped_tracking"] += 1
                    log.debug(f"Track {best_track.track_id} recently captured, skipping")
                    continue
                
                log.info(f"📸 Capturing Track ID {best_track.track_id} (state={best_track.state}, hits={best_track.hits})")
                
                # Process frame through quality filters
                should_process, enhanced_frame, metadata = self._process_frame(frame)
                if not should_process:
                    continue
                
                # Use enhanced frame if available
                frame_to_save = enhanced_frame if enhanced_frame is not None else frame
                
                # Quality Gate check
                gate_result = self.quality_gate.check(frame_to_save)
                if not gate_result.passed:
                    self.stats["frames_rejected_quality_gate"] += 1
                    log.debug(f"Track {best_track.track_id} QualityGate rejected: {gate_result.reject_reason}")
                    continue
                
                # Override quality_score
                metadata["quality_score"] = gate_result.score
                metadata["track_id"] = best_track.track_id
                
                # Save and enqueue
                try:
                    image_path = self._save_frame(frame_to_save, track_id=best_track.track_id)
                    capture_id = self._insert_capture(image_path, track_id=best_track.track_id)
                    self._enqueue_processing(capture_id, image_path)
                    
                    # Mark as captured
                    self.vehicle_tracker.mark_captured(best_track.track_id, now)
                    self.stats["frames_enqueued"] += 1
                    self.stats["vehicles_captured"] += 1
                    
                    log.info(
                        f"✅ Track {best_track.track_id} captured → capture_id={capture_id} "
                        f"(quality={gate_result.score:.0f}, total_captured={self.stats['vehicles_captured']})"
                    )
                    
                except Exception as e:
                    log.error(f"Failed to process Track {best_track.track_id}: {e}")
                
            elif not self.vehicle_tracker:
                # Tracking disabled — use old behavior (capture all frames that pass filters)
                should_process, enhanced_frame, metadata = self._process_frame(frame)
                if not should_process:
                    continue
                
                frame_to_save = enhanced_frame if enhanced_frame is not None else frame
                
                gate_result = self.quality_gate.check(frame_to_save)
                if not gate_result.passed:
                    self.stats["frames_dropped_quality"] += 1
                    continue
                
                metadata["quality_score"] = gate_result.score
                
                # Save frame to disk
                try:
                    image_path = self._save_frame(frame_to_save)
                except Exception as e:
                    log.error(f"Failed to save frame: {e}")
                    continue
                
                # Best Shot Buffer
                candidate = FrameCandidate(
                    image_path=image_path,
                    quality_score=metadata.get("quality_score", 0.0),
                    timestamp=now,
                    metadata=metadata,
                )
                selected = self.best_shot_buffer.add(candidate)
                if selected:
                    self._enqueue_selected(selected)
                
                # Check gap timeout
                gap_result = self.best_shot_buffer.check_timeout(now)
                if gap_result:
                    self._enqueue_selected(gap_result)
            
            # Update stats every 10 frames
            if self.stats["frames_read"] % 10 == 0:
                self._update_stats()
        
        # Cleanup
        self.stop()
    
    def _enqueue_selected(self, selected: FrameCandidate):
        """Enqueue the best-shot frame for processing (legacy mode)"""
        try:
            capture_id = self._insert_capture(selected.image_path)
            self._enqueue_processing(capture_id, selected.image_path)
            self.stats["frames_enqueued"] += 1
            
            if self.stats["frames_enqueued"] % 5 == 0:
                night_status = " [NIGHT]" if selected.metadata.get("is_night") else ""
                log.info(
                    f"BestShot enqueued {self.stats['frames_enqueued']} "
                    f"(read={self.stats['frames_read']}, "
                    f"score={selected.quality_score:.1f}{night_status})"
                )
        except Exception as e:
            log.error(f"Failed to enqueue selected frame: {e}")

    def stop(self):
        """Stop producer and cleanup"""
        self.running = False
        
        # Flush remaining buffer (if tracking disabled)
        if not self.vehicle_tracker:
            remaining = self.best_shot_buffer.flush_remaining()
            if remaining:
                self._enqueue_selected(remaining)
        
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        
        # Final stats update
        self._update_stats()
        
        log.info(f"Producer stopped. Stats: {self.stats}")
        if self.vehicle_tracker:
            log.info(f"  Vehicles tracked: {self.stats['vehicles_tracked']}")
            log.info(f"  Vehicles captured: {self.stats['vehicles_captured']}")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="RTSP Frame Producer for Thai ALPR (Enhanced with Vehicle Tracking)"
    )
    parser.add_argument("--camera-id", required=True, help="Camera ID")
    parser.add_argument("--rtsp-url", required=True, help="RTSP stream URL")
    parser.add_argument("--fps", type=float, default=2.0, help="Target FPS (default: 2.0)")
    parser.add_argument(
        "--enable-night-enhancement",
        action="store_true",
        default=True,
        help="Enable night-time quality enhancement (default: True)"
    )
    parser.add_argument(
        "--disable-night-enhancement",
        action="store_true",
        help="Disable night-time quality enhancement"
    )
    parser.add_argument(
        "--enable-preprocessing",
        action="store_true",
        help="Enable image preprocessing for low-light frames"
    )
    parser.add_argument(
        "--enable-tracking",
        action="store_true",
        default=True,
        help="Enable vehicle tracking (default: True)"
    )
    parser.add_argument(
        "--disable-tracking",
        action="store_true",
        help="Disable vehicle tracking"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Check feature availability
    if not NIGHT_ENHANCEMENT_AVAILABLE:
        log.warning("Night enhancement modules unavailable.")
    
    if not VEHICLE_TRACKER_AVAILABLE:
        log.warning("Vehicle tracker module unavailable.")
    
    # Create config
    config = RTSPConfig.from_env()
    config.target_fps = args.fps
    
    # Resolve flags
    enable_night = args.enable_night_enhancement and not args.disable_night_enhancement
    enable_tracking = args.enable_tracking and not args.disable_tracking
    
    # Create and run producer
    producer = RTSPFrameProducer(
        camera_id=args.camera_id,
        rtsp_url=args.rtsp_url,
        config=config,
        enable_night_enhancement=enable_night,
        enable_preprocessing=args.enable_preprocessing,
        enable_tracking=enable_tracking,
    )
    
    try:
        producer.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error(f"Producer failed: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())