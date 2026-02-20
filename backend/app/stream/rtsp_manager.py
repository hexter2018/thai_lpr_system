# backend/app/stream/rtsp_manager.py
"""
RTSP Stream Manager with Zone Trigger Logic
Supports H.264/H.265, ByteTrack integration, and polygon zone detection
"""
import asyncio
import logging
import os
import time
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

from ..db.models import Camera, VehicleTrack, CameraStats, CameraStatus, VehicleType
from ..db.session import SessionLocal

log = logging.getLogger(__name__)


@dataclass
class ZoneConfig:
    """Polygon Zone Configuration"""
    polygon: List[Tuple[int, int]]  # [(x1,y1), (x2,y2), ...]
    enabled: bool = True
    min_frames_in_zone: int = 3


@dataclass
class StreamFrame:
    """Frame from RTSP stream"""
    frame_id: int
    timestamp: datetime
    image: np.ndarray
    camera_id: str

@dataclass
class LocalTrack:
    """In-memory track state for lightweight tracking fallback."""
    track_id: int
    bbox: Tuple[int, int, int, int]
    first_seen: datetime
    last_seen: datetime
    entered_zone: bool = False
    entered_zone_at: Optional[datetime] = None
    lpr_triggered: bool = False
    lpr_triggered_at: Optional[datetime] = None
    frames_in_zone: int = 0
    missing_frames: int = 0

class RTSPStreamManager:
    """
    Manages multiple RTSP streams with zone trigger support
    
    Features:
    - Auto-reconnect on failure
    - H.264/H.265 support via OpenCV/FFmpeg
    - Background threading for continuous capture
    - MJPEG server for web preview
    - Zone trigger detection with ByteTrack
    """
    
    def __init__(
        self,
        camera_configs: Dict[str, Camera],
        redis_client,
        db_session_factory,
    ):
        self.cameras = camera_configs
        self.redis = redis_client
        self.db_factory = db_session_factory
        
        self.streams: Dict[str, cv2.VideoCapture] = {}
        self.stream_threads: Dict[str, threading.Thread] = {}
        self.frame_queues: Dict[str, queue.Queue] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        self.track_states: Dict[str, Dict[int, LocalTrack]] = defaultdict(dict)
        self.next_track_id: Dict[str, int] = defaultdict(int)
        self.detectors: Dict[str, cv2.BackgroundSubtractor] = {}
        self.last_stats_flush: Dict[str, datetime] = {}
        
        # Zone configs
        self.zones: Dict[str, ZoneConfig] = {}
        
        # MJPEG server
        self.mjpeg_enabled = os.getenv("MJPEG_SERVER_ENABLED", "true").lower() == "true"
        self.mjpeg_port = int(os.getenv("MJPEG_SERVER_PORT", "8090"))
        self.mjpeg_quality = int(os.getenv("MJPEG_QUALITY", "85"))
        
        log.info("RTSPStreamManager initialized for %d cameras", len(self.cameras))
    
    def start(self):
        """Start all camera streams"""
        for camera_id, camera in self.cameras.items():
            if camera.enabled:
                self._start_stream(camera_id, camera)
        
        if self.mjpeg_enabled:
            self._start_mjpeg_server()
    
    def stop(self):
        """Stop all streams gracefully"""
        for camera_id in list(self.streams.keys()):
            self._stop_stream(camera_id)
    
    def _start_stream(self, camera_id: str, camera: Camera):
        """Start individual RTSP stream"""
        if camera_id in self.streams:
            log.warning("Stream %s already running", camera_id)
            return
        
        # Create zone config if available
        if camera.zone_enabled and camera.zone_polygon:
            polygon = [(p['x'], p['y']) for p in camera.zone_polygon]
            self.zones[camera_id] = ZoneConfig(
                polygon=polygon,
                enabled=True,
                min_frames_in_zone=int(os.getenv("ZONE_MIN_FRAMES_IN_ZONE", "3"))
            )

        
        self.detectors[camera_id] = cv2.createBackgroundSubtractorMOG2(
            history=300,
            varThreshold=32,
            detectShadows=True,
        )
        
        # Initialize capture
        rtsp_url = camera.rtsp_url
        cap = cv2.VideoCapture(rtsp_url)
        
        # Set buffer size (reduce latency)
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
        
        # Signal stop
        self.stop_events[camera_id].set()
        
        # Wait for thread
        if camera_id in self.stream_threads:
            self.stream_threads[camera_id].join(timeout=5.0)
        
        # Release capture
        self.streams[camera_id].release()
        
        # Cleanup
        del self.streams[camera_id]
        del self.frame_queues[camera_id]
        del self.stop_events[camera_id]
        
        log.info("Stream stopped: %s", camera_id)
    
    def _capture_loop(self, camera_id: str, camera: Camera, cap: cv2.VideoCapture):
        """Continuous frame capture loop"""
        fps_target = camera.fps_target
        frame_delay = 1.0 / fps_target if fps_target > 0 else 0.1
        
        frame_id = 0
        reconnect_delay = int(os.getenv("RTSP_RECONNECT_DELAY", "5"))
        
        while not self.stop_events[camera_id].is_set():
            ret, frame = cap.read()
            
            if not ret:
                log.warning("Stream read failed: %s, reconnecting...", camera_id)
                cap.release()
                time.sleep(reconnect_delay)
                cap = cv2.VideoCapture(camera.rtsp_url)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                continue
            
            # Create stream frame
            stream_frame = StreamFrame(
                frame_id=frame_id,
                timestamp=datetime.utcnow(),
                image=frame.copy(),
                camera_id=camera_id
            )
            
            # Put in queue (non-blocking, drop if full)
            try:
                self.frame_queues[camera_id].put_nowait(stream_frame)
            except queue.Full:
                pass  # Drop frame if queue full
            
            try:
                self._process_tracking(camera_id, frame, stream_frame.timestamp)
            except Exception as e:
                log.exception("Tracking pipeline failed for %s: %s", camera_id, e)

            frame_id += 1
            
            # FPS throttle
            if frame_delay > 0:
                time.sleep(frame_delay)
    
    def get_latest_frame(self, camera_id: str) -> Optional[StreamFrame]:
        """Get latest frame from queue"""
        if camera_id not in self.frame_queues:
            return None
        
        try:
            # Get latest, discard old
            frame = None
            while not self.frame_queues[camera_id].empty():
                frame = self.frame_queues[camera_id].get_nowait()
            return frame
        except queue.Empty:
            return None
    
    
    def _process_tracking(self, camera_id: str, frame: np.ndarray, ts: datetime):
        """Lightweight vehicle detection+tracking+zone trigger pipeline."""
        detector = self.detectors.get(camera_id)
        if detector is None:
            return

        fg = detector.apply(frame)
        fg = cv2.GaussianBlur(fg, (5, 5), 0)
        _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
        kernel = np.ones((5, 5), np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)
        fg = cv2.morphologyEx(fg, cv2.MORPH_DILATE, kernel, iterations=2)

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: List[Tuple[int, int, int, int]] = []

        min_area = int(os.getenv("TRACK_MIN_BLOB_AREA", "2500"))
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 40 or h < 30:
                continue
            detections.append((x, y, x + w, y + h))

        self._update_tracks(camera_id, detections, ts)
        self._flush_stats_if_needed(camera_id, ts)

    def _update_tracks(self, camera_id: str, detections: List[Tuple[int, int, int, int]], ts: datetime):
        tracks = self.track_states[camera_id]
        unmatched_track_ids = set(tracks.keys())

        # Greedy IoU matching
        for det in detections:
            best_track_id = None
            best_iou = 0.0
            for track_id in list(unmatched_track_ids):
                iou = self._iou(det, tracks[track_id].bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_track_id = track_id

            if best_track_id is not None and best_iou >= float(os.getenv("TRACK_IOU_THRESH", "0.20")):
                track = tracks[best_track_id]
                track.bbox = det
                track.last_seen = ts
                track.missing_frames = 0
                unmatched_track_ids.discard(best_track_id)
            else:
                self.next_track_id[camera_id] += 1
                tid = self.next_track_id[camera_id]
                tracks[tid] = LocalTrack(track_id=tid, bbox=det, first_seen=ts, last_seen=ts)

        # age unmatched tracks and evict stale ones
        max_missing = int(os.getenv("TRACK_MAX_MISSING_FRAMES", "15"))
        for track_id in list(unmatched_track_ids):
            tracks[track_id].missing_frames += 1
            if tracks[track_id].missing_frames > max_missing:
                del tracks[track_id]

        # zone-trigger + db upsert for active tracks only
        self._upsert_active_tracks(camera_id, ts)

    def _upsert_active_tracks(self, camera_id: str, ts: datetime):
        tracks = self.track_states[camera_id]
        zone = self.zones.get(camera_id)
        min_frames_in_zone = zone.min_frames_in_zone if zone else 3

        db = SessionLocal()
        try:
            for state in tracks.values():
                if state.missing_frames > 0:
                    continue

                if zone and not state.lpr_triggered:
                    cx = (state.bbox[0] + state.bbox[2]) // 2
                    cy = (state.bbox[1] + state.bbox[3]) // 2
                    in_zone = self.is_point_in_zone((cx, cy), zone)
                    if in_zone:
                        state.frames_in_zone += 1
                        if not state.entered_zone:
                            state.entered_zone = True
                            state.entered_zone_at = ts
                        if state.frames_in_zone >= min_frames_in_zone:
                            state.lpr_triggered = True
                            state.lpr_triggered_at = ts
                    else:
                        state.frames_in_zone = 0

                db_track = db.execute(
                    select(VehicleTrack).where(
                        and_(
                            VehicleTrack.camera_id == camera_id,
                            VehicleTrack.track_id == state.track_id,
                        )
                    )
                ).scalar_one_or_none()

                bbox_json = {
                    "x1": int(state.bbox[0]),
                    "y1": int(state.bbox[1]),
                    "x2": int(state.bbox[2]),
                    "y2": int(state.bbox[3]),
                }

                if db_track is None:
                    db_track = VehicleTrack(
                        camera_id=camera_id,
                        track_id=state.track_id,
                        vehicle_type=VehicleType.UNKNOWN,
                        entered_zone=state.entered_zone,
                        entered_zone_at=state.entered_zone_at,
                        lpr_triggered=state.lpr_triggered,
                        lpr_triggered_at=state.lpr_triggered_at,
                        bbox=bbox_json,
                        first_seen=state.first_seen,
                        last_seen=state.last_seen,
                    )
                    db.add(db_track)
                else:
                    db_track.last_seen = state.last_seen
                    db_track.entered_zone = state.entered_zone
                    db_track.entered_zone_at = state.entered_zone_at
                    db_track.lpr_triggered = state.lpr_triggered
                    db_track.lpr_triggered_at = state.lpr_triggered_at
                    db_track.bbox = bbox_json

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _flush_stats_if_needed(self, camera_id: str, ts: datetime):
        prev = self.last_stats_flush.get(camera_id)
        if prev and (ts - prev).total_seconds() < 2:
            return

        active_states = [s for s in self.track_states[camera_id].values() if s.missing_frames == 0]
        stats = CameraStats(
            camera_id=camera_id,
            fps_actual=float(len(active_states)),
            vehicle_count=len(active_states),
            lpr_success_count=sum(1 for s in active_states if s.lpr_triggered),
            lpr_fail_count=0,
            success_rate=(
                float(sum(1 for s in active_states if s.lpr_triggered) * 100 / len(active_states))
                if active_states else 0.0
            ),
            window_start=ts,
            window_end=ts,
        )

        db = SessionLocal()
        try:
            db.add(stats)
            db.commit()
            self.last_stats_flush[camera_id] = ts
        finally:
            db.close()

    def _iou(self, a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / float(area_a + area_b - inter)
    
    def is_point_in_zone(
        self,
        point: Tuple[int, int],
        zone: ZoneConfig
    ) -> bool:
        """Check if point is inside polygon zone"""
        if not zone.enabled:
            return False
        
        x, y = point
        polygon = np.array(zone.polygon, dtype=np.int32)
        result = cv2.pointPolygonTest(polygon, (float(x), float(y)), False)
        return result >= 0
    

    def draw_zone_overlay(
        self,
        frame: np.ndarray,
        camera_id: str
    ) -> np.ndarray:
        """Draw zone polygon on frame for visualization"""
        if camera_id not in self.zones:
            return frame
        
        zone = self.zones[camera_id]
        overlay = frame.copy()
        polygon = np.array(zone.polygon, dtype=np.int32)
        
        # Draw filled polygon with transparency
        cv2.fillPoly(overlay, [polygon], (0, 255, 0))
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        
        # Draw polygon border
        cv2.polylines(frame, [polygon], True, (0, 255, 0), 2)
        
        return frame
    
    def _start_mjpeg_server(self):
        """Start MJPEG server for web streaming"""
        from aiohttp import web
        
        async def mjpeg_handler(request):
            camera_id = request.match_info.get('camera_id')
            
            if camera_id not in self.frame_queues:
                return web.Response(status=404, text="Camera not found")
            
            response = web.StreamResponse()
            response.content_type = 'multipart/x-mixed-replace; boundary=frame'
            await response.prepare(request)
            
            try:
                while True:
                    frame_obj = self.get_latest_frame(camera_id)
                    if frame_obj is None:
                        await asyncio.sleep(0.1)
                        continue
                    
                    # Draw zone overlay
                    frame = self.draw_zone_overlay(frame_obj.image, camera_id)
                    
                    # Encode JPEG
                    _, jpeg = cv2.imencode(
                        '.jpg',
                        frame,
                        [cv2.IMWRITE_JPEG_QUALITY, self.mjpeg_quality]
                    )
                    
                    # Send frame
                    await response.write(
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' +
                        jpeg.tobytes() +
                        b'\r\n'
                    )
                    
                    await asyncio.sleep(0.05)  # ~20 FPS
            except Exception as e:
                log.error("MJPEG stream error: %s", e)
            
            return response
        
        app = web.Application()
        app.router.add_get('/stream/{camera_id}', mjpeg_handler)
        
        async def start_server():
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', self.mjpeg_port)
            await site.start()
            log.info("MJPEG server started on port %d", self.mjpeg_port)
        
        asyncio.create_task(start_server())
        
# Backward-compatible export name used by stream package imports.
RTSPManager = RTSPStreamManager