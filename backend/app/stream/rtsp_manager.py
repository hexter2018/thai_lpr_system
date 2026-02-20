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

from ..db.models import Camera, VehicleTrack, CameraStatus

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