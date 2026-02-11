#!/usr/bin/env python3
"""
RTSP Frame Producer for Thai ALPR System (Enhanced)

Features:
- RTSP stream reading with auto-reconnect
- Motion detection filter
- Quality scoring with day/night adaptive thresholds
- Enhanced quality filter v2 (glare detection, contrast analysis)
- Image preprocessing (CLAHE, denoising, sharpening)
- Frame deduplication
- Celery task enqueue

Night Enhancement:
- Auto-detects day/night conditions
- Applies adaptive quality thresholds
- Optional preprocessing pipeline for low-light frames
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

# Import night enhancement modules (optional)
try:
    from alpr_worker.rtsp.quality_filter_v2 import EnhancedQualityScorer
    from alpr_worker.rtsp.preprocessing import ImagePreprocessor
    NIGHT_ENHANCEMENT_AVAILABLE = True
except ImportError:
    NIGHT_ENHANCEMENT_AVAILABLE = False
    EnhancedQualityScorer = None
    ImagePreprocessor = None
    logging.warning("Night enhancement modules not available (quality_filter_v2, preprocessing)")

log = logging.getLogger(__name__)

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Bangkok


class RTSPFrameProducer:
    """
    RTSP Frame Producer with Night Enhancement Support
    
    Features:
    - Read RTSP stream with auto-reconnect
    - Filter frames: motion detection, quality check, deduplication
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
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.config = config or RTSPConfig.from_env()
        
        # Night enhancement flags
        self.enable_night_enhancement = enable_night_enhancement and NIGHT_ENHANCEMENT_AVAILABLE
        self.enable_preprocessing = enable_preprocessing and NIGHT_ENHANCEMENT_AVAILABLE
        
        # Database
        self.engine = create_engine(self.config.database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)
        
        # Redis
        self.redis = Redis.from_url(self.config.redis_url)
        
        # Storage
        self.storage_dir = Path(self.config.storage_dir)
        self.rtsp_dir = self.storage_dir / "rtsp" / camera_id
        self.rtsp_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup filters (with night enhancement if available)
        self._setup_filters()
        
        # Stats
        self.stats = {
            "frames_read": 0,
            "frames_dropped_motion": 0,
            "frames_dropped_quality": 0,
            "frames_dropped_duplicate": 0,
            "frames_dropped_line": 0,
            "frames_enhanced": 0,
            "frames_preprocessed": 0,
            "frames_enqueued": 0,
            "frames_buffered": 0,
            "frames_discarded_by_bestshot": 0,
            "frames_rejected_quality_gate": 0,
            "night_mode_active": False,
            "last_update": None,
        }
        
        # Quality Gate + Best Shot Buffer
        self.quality_gate = QualityGate()
        self.best_shot_buffer = BestShotBuffer()
        

        # Optional virtual line trigger
        self.line_trigger = VirtualLineTrigger(LineTriggerConfig.from_env())
        
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
        
        log.info("RTSP stream connected")
        return True
    
    def _save_frame(self, frame: np.ndarray) -> str:
        """Save frame to disk and return path"""
        timestamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S_%f")
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
    
    def _insert_capture(self, image_path: str) -> int:
        """
        Insert capture record into database
        Returns capture_id
        """
        db = self.Session()
        try:
            sha256 = self._sha256_file(image_path)
            
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
        """Main loop"""
        self.running = True
        frame_interval = 1.0 / self.config.target_fps
        
        log.info(f"Starting RTSP producer for {self.camera_id}")
        log.info(f"Target FPS: {self.config.target_fps}")
        log.info(f"Filters: motion={self.config.enable_motion_filter} "
                f"quality={'enhanced_v2' if self.enable_night_enhancement else 'standard'} "
                f"dedup={self.config.enable_dedup} "
                f"preprocessing={self.enable_preprocessing}")
        
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
            
            # FPS throttling
            now = time.time()
            if (now - self.last_frame_time) < frame_interval:
                continue
            self.last_frame_time = now
            
            if self.line_trigger.enabled and not self.line_trigger.check(frame, now):
                self.stats["frames_dropped_line"] += 1
                continue
        
            # Process frame through filters
            should_process, enhanced_frame, metadata = self._process_frame(frame)
            if not should_process:
                continue
            
            # Use enhanced frame if available, otherwise original
            frame_to_save = enhanced_frame if enhanced_frame is not None else frame
            
            # Quality Gate: reject junk frames early
            gate_result = self.quality_gate.check(frame_to_save)
            if not gate_result.passed:
                self.stats["frames_dropped_quality"] += 1
                log.debug("QualityGate rejected: %s (score=%.0f)", gate_result.reject_reason, gate_result.score)
                continue
            
            # Override quality_score with gate score for better best-shot selection
            metadata["quality_score"] = gate_result.score
            
            # Save frame to disk (needed for buffer)
            try:
                image_path = self._save_frame(frame_to_save)
            except Exception as e:
                log.error(f"Failed to save frame: {e}")
                continue
            
            # Best Shot Buffer: buffer frame, only enqueue when best is selected
            candidate = FrameCandidate(
                image_path=image_path,
                quality_score=metadata.get("quality_score", 0.0),
                timestamp=now,
                metadata=metadata,
            )
            selected = self.best_shot_buffer.add(candidate)
            if selected:
                self._enqueue_selected(selected)
            
            # Best Shot: check gap timeout (no new frames → flush buffer)
            gap_result = self.best_shot_buffer.check_timeout(now)
            if gap_result:
                self._enqueue_selected(gap_result)
            
            # Update stats every 10 frames
            if self.stats["frames_enqueued"] % 10 == 0:
                self._update_stats()
        
        # Cleanup
        self.stop()
    
    def _enqueue_selected(self, selected: FrameCandidate):
        """Enqueue the best-shot frame for processing"""
        try:
            capture_id = self._insert_capture(selected.image_path)
            self._enqueue_processing(capture_id, selected.image_path)
            self.stats["frames_enqueued"] += 1
            
            if self.stats["frames_enqueued"] % 5 == 0:
                night_status = " [NIGHT]" if selected.metadata.get("is_night") else ""
                buffered = self.best_shot_buffer.buffered_count
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
        
        # Flush remaining buffer
        remaining = self.best_shot_buffer.flush_remaining()
        if remaining:
            self._enqueue_selected(remaining)
        
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        
        # Final stats update
        self._update_stats()
        
        log.info(f"Producer stopped. Stats: {self.stats}")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="RTSP Frame Producer for Thai ALPR (Enhanced)"
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
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Check night enhancement availability
    if not NIGHT_ENHANCEMENT_AVAILABLE:
        log.warning(
            "Night enhancement modules not available. "
            "To enable, ensure quality_filter_v2.py and preprocessing.py are in rtsp/ directory."
        )
    
    # Create config
    config = RTSPConfig.from_env()
    config.target_fps = args.fps
    
    # Resolve night enhancement flag
    enable_night = args.enable_night_enhancement and not args.disable_night_enhancement
    
    # Create and run producer
    producer = RTSPFrameProducer(
        camera_id=args.camera_id,
        rtsp_url=args.rtsp_url,
        config=config,
        enable_night_enhancement=enable_night,
        enable_preprocessing=args.enable_preprocessing,
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