# backend/app/stream/rtsp_manager.py
"""
RTSP Stream Manager with Line Crossing & Trajectory Tracking
Uses TensorRT vehicle detection (models/vehicles.engine) + LPR tracking engine
"""
import asyncio
import base64
import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import cv2
import numpy as np
from datetime import datetime
import threading
import queue
from collections import defaultdict

from sqlalchemy import and_, select

from ..core.config import settings
from ..db.models import Camera, VehicleTrack, CameraStats, CameraStatus, VehicleType, Capture
from ..db.session import SessionLocal

try:
    from worker.tracking.bytetrack_engine import LPRTrackingEngine, Detection

except ImportError:
    # Fallback สำหรับ local development
    import sys

    candidate_worker_paths = [
        Path(__file__).resolve().parents[3] / "worker",
        Path(__file__).resolve().parents[2] / "worker",
        Path.cwd() / "worker",
    ]
    for worker_path in candidate_worker_paths:
        if worker_path.exists() and str(worker_path) not in sys.path:
            sys.path.insert(0, str(worker_path))

    from worker.tracking.bytetrack_engine import LPRTrackingEngine, Detection

try:
    from worker.alpr_worker.tasks import process_lpr_task
except ImportError:
    process_lpr_task = None
    log = logging.getLogger(__name__)
    log.warning("LPR Celery task import failed; LPR dispatch will be retried lazily")    

log = logging.getLogger(__name__)


# =============================================
# TensorRT Vehicle Detector
# =============================================
USE_TRT_VEHICLE_DETECTOR = os.getenv("USE_TRT_VEHICLE_DETECTOR", "true").lower() == "true"

if USE_TRT_VEHICLE_DETECTOR:
    try:
        from worker.alpr_worker.inference.trt.yolov8_trt_detector import YOLOv8TRTPlateDetector
        
        class VehicleDetector:
            """TensorRT vehicle detector wrapper (uses models/vehicles.engine)"""
            def __init__(self):
                # Override MODEL_PATH temporarily for vehicle detection
                original_model_path = os.getenv("MODEL_PATH")
                os.environ["MODEL_PATH"] = "/models/vehicles.engine"
                
                try:
                    self.detector = YOLOv8TRTPlateDetector()
                    log.info("VehicleDetector initialized with TensorRT: /models/vehicles.engine")
                finally:
                    # Restore original MODEL_PATH
                    if original_model_path:
                        os.environ["MODEL_PATH"] = original_model_path
                    else:
                        os.environ.pop("MODEL_PATH", None)
            
            def detect(self, frame: np.ndarray) -> List[Detection]:
                """Run vehicle detection on frame"""
                try:
                    # Preprocess
                    inp, lb = self.detector._preprocess(frame)
                    
                    # Infer
                    y = self.detector.trt.infer(inp)
                    
                    # Decode
                    boxes_inp, scores, class_ids = self.detector._decode_outputs(y)
                    
                    if boxes_inp.size == 0:
                        return []
                    
                    # NMS
                    from alpr_worker.inference.trt.yolov8_trt_detector import nms_xyxy
                    keep_idx = nms_xyxy(boxes_inp, scores, self.detector.iou_thres)
                    boxes_inp = boxes_inp[keep_idx]
                    scores = scores[keep_idx]
                    class_ids = class_ids[keep_idx]
                    
                    # Scale back to original frame
                    h0, w0 = frame.shape[:2]
                    boxes_orig = self.detector._scale_boxes_back(boxes_inp, lb, (h0, w0))
                    
                    # Convert to Detection objects
                    detections = []
                    for i in range(len(boxes_orig)):
                        bbox = tuple(map(int, boxes_orig[i]))
                        det = Detection(
                            bbox=bbox,
                            score=float(scores[i]),
                            class_id=int(class_ids[i]),
                        )
                        detections.append(det)
                    
                    return detections
                
                except Exception as e:
                    log.error("Vehicle detection failed: %s", e)
                    return []
        
        log.info("Using TensorRT for vehicle detection")
    
    except ImportError as e:
        log.warning("TensorRT not available for vehicle detection, using fallback: %s", e)
        USE_TRT_VEHICLE_DETECTOR = False


if not USE_TRT_VEHICLE_DETECTOR:
    # Fallback: simple background subtraction (lightweight)
    class VehicleDetector:
        """Fallback vehicle detector using background subtraction"""
        def __init__(self):
            self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                history=300,
                varThreshold=32,
                detectShadows=True,
            )
            log.info("VehicleDetector initialized with background subtraction (fallback)")
        
        def detect(self, frame: np.ndarray) -> List[Detection]:
            """Simple blob detection"""
            fg = self.bg_subtractor.apply(frame)
            fg = cv2.GaussianBlur(fg, (5, 5), 0)
            _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
            kernel = np.ones((5, 5), np.uint8)
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)
            fg = cv2.morphologyEx(fg, cv2.MORPH_DILATE, kernel, iterations=2)
            
            contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            detections = []
            
            min_area = int(os.getenv("VEHICLE_MIN_BLOB_AREA", "5000"))
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if w < 50 or h < 40:
                    continue
                bbox = (x, y, x + w, y + h)
                det = Detection(bbox=bbox, score=0.7, class_id=0)
                detections.append(det)
            
            return detections


@dataclass
class StreamFrame:
    """Frame from RTSP stream"""
    frame_id: int
    timestamp: datetime
    image: np.ndarray
    camera_id: str


class RTSPStreamManager:
    """
    Manages RTSP streams with line crossing detection & LPR triggering
    
    Features:
    - TensorRT vehicle detection (models/vehicles.engine)
    - Trajectory tracking with ByteTrack
    - Virtual line crossing detection
    - Best crop buffering
    - Async LPR processing via Celery
    """
    
    def __init__(
        self,
        camera_configs: Dict[str, Camera],
        redis_client,
        db_session_factory,
        count_line: Optional[List[Tuple[int, int]]] = None,
    ):
        self.cameras = camera_configs
        self.redis = redis_client
        self.db_factory = db_session_factory
        self.count_line = count_line or [(100, 400), (900, 400)]  # Default horizontal line
        
        self.streams: Dict[str, cv2.VideoCapture] = {}
        self.stream_threads: Dict[str, threading.Thread] = {}
        self.frame_queues: Dict[str, queue.Queue] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        
        # Vehicle detector (TensorRT)
        self.vehicle_detector = VehicleDetector()
        
        # LPR Tracking engines per camera
        self.tracking_engines: Dict[str, LPRTrackingEngine] = {}
        
        self.last_stats_flush: Dict[str, datetime] = {}
        
        log.info("RTSPStreamManager initialized for %d cameras", len(self.cameras))
        log.info("Count line: %s", self.count_line)
    
    def start(self):
        """Start all camera streams"""
        for camera_id, camera in self.cameras.items():
            if camera.enabled:
                self._start_stream(camera_id, camera)
    
    def stop(self):
        """Stop all streams gracefully"""
        for camera_id in list(self.streams.keys()):
            self._stop_stream(camera_id)
    
    def _start_stream(self, camera_id: str, camera: Camera):
        """Start individual RTSP stream"""
        if camera_id in self.streams:
            log.warning("Stream %s already running", camera_id)
            return
        
        # Initialize tracking engine for this camera
        self.tracking_engines[camera_id] = LPRTrackingEngine(
            count_line=self.count_line,
            track_thresh=0.45,
            track_buffer=30,
            trajectory_maxlen=30,
        )
        
        # Initialize capture
        rtsp_url = camera.rtsp_url
        cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, int(os.getenv("RTSP_BUFFER_SIZE", "2")))
        
        if not cap.isOpened():
            log.error("Failed to open stream: %s", camera_id)
            return
        
        self.streams[camera_id] = cap
        self.frame_queues[camera_id] = queue.Queue(maxsize=30)
        self.stop_events[camera_id] = threading.Event()
        
        # Start capture thread
        thread = threading.Thread(
            target=self._capture_loop,
            args=(camera_id, camera, cap),
            daemon=True
        )
        thread.start()
        self.stream_threads[camera_id] = thread
        
        log.info("Stream started: %s (%s)", camera_id, camera.name)
    
    def _stop_stream(self, camera_id: str):
        """Stop individual stream"""
        if camera_id not in self.streams:
            return
        
        self.stop_events[camera_id].set()
        
        if camera_id in self.stream_threads:
            self.stream_threads[camera_id].join(timeout=5.0)
        
        self.streams[camera_id].release()
        
        del self.streams[camera_id]
        del self.frame_queues[camera_id]
        del self.stop_events[camera_id]
        
        if camera_id in self.tracking_engines:
            del self.tracking_engines[camera_id]
        
        log.info("Stream stopped: %s", camera_id)
    
    def _capture_loop(self, camera_id: str, camera: Camera, cap: cv2.VideoCapture):
        """Continuous frame capture & tracking loop"""
        fps_target = camera.fps_target or 10
        frame_delay = 1.0 / fps_target if fps_target > 0 else 0.1
        
        frame_id = 0
        reconnect_delay = int(os.getenv("RTSP_RECONNECT_DELAY", "5"))
        
        tracker = self.tracking_engines.get(camera_id)
        if tracker is None:
            log.error("No tracking engine for camera %s", camera_id)
            return
        
        while not self.stop_events[camera_id].is_set():
            ret, frame = cap.read()
            
            if not ret:
                log.warning("Stream read failed: %s, reconnecting...", camera_id)
                cap.release()
                time.sleep(reconnect_delay)
                cap = cv2.VideoCapture(camera.rtsp_url)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                continue
            
            timestamp = datetime.utcnow()
            
            # Create stream frame
            stream_frame = StreamFrame(
                frame_id=frame_id,
                timestamp=timestamp,
                image=frame.copy(),
                camera_id=camera_id
            )
            
            # Put in queue (non-blocking, drop if full)
            try:
                self.frame_queues[camera_id].put_nowait(stream_frame)
            except queue.Full:
                pass
            
            # =============================================
            # TRACKING & LPR TRIGGER PIPELINE
            # =============================================
            try:
                # 1) Vehicle Detection (TensorRT)
                detections = self.vehicle_detector.detect(frame)
                
                # 2) Update tracker & check line crossings
                trigger_ocr_list, vehicle_count = tracker.update(detections, frame)
                
                # 3) Process LPR triggers
                for event in trigger_ocr_list:
                    self._dispatch_lpr_task(
                        camera_id=camera_id,
                        track_id=event.track_id,
                        vehicle_count=event.count_id,
                        vehicle_crop=event.vehicle_crop,
                    )
                
                # 4) Flush stats periodically
                self._flush_stats_if_needed(camera_id, timestamp, tracker)
            
            except Exception as e:
                log.exception("Tracking pipeline failed for %s: %s", camera_id, e)
            
            frame_id += 1
            
            # FPS throttle
            if frame_delay > 0:
                time.sleep(frame_delay)
    
    def _dispatch_lpr_task(
        self,
        camera_id: str,
        track_id: int,
        vehicle_count: int,
        vehicle_crop: np.ndarray,
    ):
        """Dispatch LPR processing task to Celery worker"""
        try:

            global process_lpr_task

            if process_lpr_task is None:
                from worker.alpr_worker.tasks import process_lpr_task as imported_task
                process_lpr_task = imported_task


            # Encode vehicle crop to Base64
            ok, encoded = cv2.imencode('.jpg', vehicle_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if not ok:
                log.error(
                    "Failed to encode vehicle crop (track_id=%d, count=%d)",
                    track_id, vehicle_count
                )
                return
            
            vehicle_crop_b64 = base64.b64encode(encoded.tobytes()).decode('utf-8')
            
            # Send to Celery
            process_lpr_task.delay(
                vehicle_crop_b64=vehicle_crop_b64,
                track_id=track_id,
                vehicle_count=vehicle_count,
                camera_id=camera_id,
            )
            
            log.info(
                "📤 LPR task dispatched: camera=%s, track_id=%d, count=%d, crop_size=%d bytes",
                camera_id, track_id, vehicle_count, len(vehicle_crop_b64)
            )
        
        except Exception as e:
            log.error(
                "Failed to dispatch LPR task (track_id=%d, count=%d): %s",
                track_id, vehicle_count, e
            )
    
    def _flush_stats_if_needed(
        self,
        camera_id: str,
        ts: datetime,
        tracker: LPRTrackingEngine,
    ):
        """Flush camera stats to database periodically"""
        prev = self.last_stats_flush.get(camera_id)
        if prev and (ts - prev).total_seconds() < 5:
            return
        
        stats_data = tracker.get_stats()
        
        stats = CameraStats(
            camera_id=camera_id,
            fps_actual=10.0,  # Placeholder
            vehicle_count=stats_data["vehicle_count"],
            lpr_success_count=stats_data["crossed_tracks"],
            lpr_fail_count=0,
            success_rate=100.0 if stats_data["vehicle_count"] > 0 else 0.0,
            window_start=ts,
            window_end=ts,
        )
        
        db = SessionLocal()
        try:
            db.add(stats)
            db.commit()
            self.last_stats_flush[camera_id] = ts
        except Exception as e:
            log.error("Failed to flush stats for %s: %s", camera_id, e)
        finally:
            db.close()
    
    def get_latest_frame(self, camera_id: str) -> Optional[StreamFrame]:
        """Get latest frame from queue"""
        if camera_id not in self.frame_queues:
            return None
        
        try:
            frame = None
            while not self.frame_queues[camera_id].empty():
                frame = self.frame_queues[camera_id].get_nowait()
            return frame
        except queue.Empty:
            return None


# Backward-compatible export
RTSPManager = RTSPStreamManager