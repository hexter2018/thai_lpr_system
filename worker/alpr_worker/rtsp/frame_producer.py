#!/usr/bin/env python3
"""
RTSP Frame Producer for Thai ALPR System

อ่าน RTSP stream, filter frames (motion + quality + dedup), 
แล้วเรียก existing process_capture task ผ่าน Celery
"""

import argparse
import hashlib
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import existing modules
from alpr_worker.rtsp.quality_filter import MotionDetector, QualityScorer, FrameDeduplicator
from alpr_worker.rtsp.config import RTSPConfig
from alpr_worker.celery_app import celery_app

log = logging.getLogger(__name__)


class RTSPFrameProducer:
    """
    RTSP Frame Producer
    
    Features:
    - Read RTSP stream with auto-reconnect
    - Filter frames: motion detection, quality check, deduplication
    - Save frames and enqueue to existing process_capture task
    - Track statistics in Redis
    """
    
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        config: Optional[RTSPConfig] = None
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.config = config or RTSPConfig.from_env()
        
        # Database
        self.engine = create_engine(self.config.database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)
        
        # Redis
        self.redis = Redis.from_url(self.config.redis_url)
        
        # Storage
        self.storage_dir = Path(self.config.storage_dir)
        self.rtsp_dir = self.storage_dir / "rtsp" / camera_id
        self.rtsp_dir.mkdir(parents=True, exist_ok=True)
        
        # Filters
        self.motion_detector = MotionDetector(
            threshold=self.config.motion_threshold
        ) if self.config.enable_motion_filter else None
        
        self.quality_scorer = QualityScorer(
            min_score=self.config.min_quality_score
        ) if self.config.enable_quality_filter else None
        
        self.deduplicator = FrameDeduplicator(
            cache_size=self.config.dedup_cache_size,
            threshold=self.config.dedup_threshold
        ) if self.config.enable_dedup else None
        
        # Stats
        self.stats = {
            "frames_read": 0,
            "frames_dropped_motion": 0,
            "frames_dropped_quality": 0,
            "frames_dropped_duplicate": 0,
            "frames_enqueued": 0,
            "last_update": None,
        }
        
        # State
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.last_frame_time = 0.0
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
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
            self.stats["last_update"] = datetime.utcnow().isoformat()
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
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
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
                "captured_at": datetime.utcnow(),
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
    
    def _process_frame(self, frame: np.ndarray) -> bool:
        """
        Process single frame through filters
        Returns True if frame should be processed, False if dropped
        """
        # Motion filter
        if self.motion_detector:
            if not self.motion_detector.has_motion(frame):
                self.stats["frames_dropped_motion"] += 1
                return False
        
        # Quality filter
        if self.quality_scorer:
            score = self.quality_scorer.score(frame)
            if score < self.config.min_quality_score:
                self.stats["frames_dropped_quality"] += 1
                return False
        
        # Deduplication filter
        if self.deduplicator:
            if self.deduplicator.is_duplicate(frame):
                self.stats["frames_dropped_duplicate"] += 1
                return False
        
        return True
    
    def run(self):
        """Main loop"""
        self.running = True
        frame_interval = 1.0 / self.config.target_fps
        
        log.info(f"Starting RTSP producer for {self.camera_id}")
        log.info(f"Target FPS: {self.config.target_fps}")
        log.info(f"Filters: motion={self.config.enable_motion_filter} "
                f"quality={self.config.enable_quality_filter} "
                f"dedup={self.config.enable_dedup}")
        
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
            
            # Process frame through filters
            if not self._process_frame(frame):
                continue
            
            # Save frame
            try:
                image_path = self._save_frame(frame)
                
                # Insert capture record
                capture_id = self._insert_capture(image_path)
                
                # Enqueue for processing (existing task)
                self._enqueue_processing(capture_id, image_path)
                
                self.stats["frames_enqueued"] += 1
                
                if self.stats["frames_enqueued"] % 10 == 0:
                    log.info(f"Enqueued {self.stats['frames_enqueued']} frames "
                            f"(read={self.stats['frames_read']}, "
                            f"dropped={self.stats['frames_dropped_motion'] + self.stats['frames_dropped_quality'] + self.stats['frames_dropped_duplicate']})")
                
            except Exception as e:
                log.error(f"Failed to process frame: {e}")
                continue
            
            # Update stats every 10 frames
            if self.stats["frames_enqueued"] % 10 == 0:
                self._update_stats()
        
        # Cleanup
        self.stop()
    
    def stop(self):
        """Stop producer and cleanup"""
        self.running = False
        
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        
        # Final stats update
        self._update_stats()
        
        log.info(f"Producer stopped. Stats: {self.stats}")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="RTSP Frame Producer for Thai ALPR")
    
    # ✅ ใช้ env vars เป็น default
    parser.add_argument(
        "--camera-id",
        default=os.getenv("CAMERA_ID"),
        help="Camera ID (default: from CAMERA_ID env var)"
    )
    parser.add_argument(
        "--rtsp-url",
        default=os.getenv("RTSP_URL"),
        help="RTSP stream URL (default: from RTSP_URL env var)"
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=float(os.getenv("RTSP_TARGET_FPS", "2.0")),
        help="Target FPS (default: 2.0 or from RTSP_TARGET_FPS env var)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # ✅ Validate required arguments
    if not args.camera_id:
        parser.error("--camera-id is required (or set CAMERA_ID environment variable)")
    if not args.rtsp_url:
        parser.error("--rtsp-url is required (or set RTSP_URL environment variable)")
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Create config
    config = RTSPConfig.from_env()
    config.target_fps = args.fps
    
    log.info(f"Starting RTSP Frame Producer")
    log.info(f"Camera ID: {args.camera_id}")
    log.info(f"RTSP URL: {args.rtsp_url[:50]}...")  # แสดงแค่ 50 ตัวแรก (ไม่เปิดเผย password)
    log.info(f"Target FPS: {args.fps}")
    log.info(f"Config: {config}")
    
    # Create and run producer
    producer = RTSPFrameProducer(
        camera_id=args.camera_id,
        rtsp_url=args.rtsp_url,
        config=config,
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