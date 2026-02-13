"""
web_dashboard.py — Web-based Live ALPR Dashboard
=================================================

Flask web dashboard with:
- Live MJPEG video streams
- Real-time stats updates
- Multi-camera grid view
- Vehicle tracking visualization
- Capture history

Usage:
    python web_dashboard.py
    
Access:
    http://localhost:5000
"""

from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS
import cv2
import json
import logging
import numpy as np
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Lock
from typing import Dict, Optional, List

from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import ALPR modules
try:
    from alpr_worker.rtsp.vehicle_tracker import VehicleTracker, create_tracker_from_env
    from alpr_worker.rtsp.zone_trigger import ZoneTrigger, load_zones_from_env
    from alpr_worker.rtsp.config import RTSPConfig
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)

config = RTSPConfig.from_env() if MODULES_AVAILABLE else None
redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


# ═══════════════════════════════════════════════════════════════
# Camera Manager
# ═══════════════════════════════════════════════════════════════

class CameraStream:
    """Single camera stream with tracking visualization"""
    
    def __init__(self, camera_id: str, rtsp_url: str):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame: Optional[np.ndarray] = None
        self.lock = Lock()
        self.running = False
        self.thread: Optional[Thread] = None
        
        # Tracking
        self.vehicle_tracker: Optional[VehicleTracker] = None
        self.zone_trigger: Optional[ZoneTrigger] = None
        
        if MODULES_AVAILABLE:
            self.vehicle_tracker = create_tracker_from_env()
            zones = load_zones_from_env()
            if zones:
                self.zone_trigger = ZoneTrigger(zones)
        
        # Stats
        self.fps = 0.0
        self.last_update = time.time()
    
    def connect(self):
        """Connect to RTSP stream"""
        if self.cap is not None:
            self.cap.release()
        
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        return self.cap.isOpened()
    
    def start(self):
        """Start capture thread"""
        if self.running:
            return
        
        self.running = True
        self.thread = Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        log.info(f"Started stream for {self.camera_id}")
    
    def stop(self):
        """Stop capture thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
    
    def _capture_loop(self):
        """Capture loop (runs in thread)"""
        if not self.connect():
            log.error(f"Failed to connect: {self.camera_id}")
            return
        
        while self.running:
            ret, frame = self.cap.read()
            
            if not ret or frame is None:
                log.warning(f"Failed to read frame: {self.camera_id}")
                time.sleep(1.0)
                self.connect()
                continue
            
            # Calculate FPS
            now = time.time()
            dt = now - self.last_update
            self.last_update = now
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)  # Smoothed FPS
            
            # Process frame
            frame = self._process_frame(frame, now)
            
            # Store frame
            with self.lock:
                self.frame = frame
            
            # Throttle to ~15 FPS
            time.sleep(0.066)
    
    def _process_frame(self, frame: np.ndarray, timestamp: float) -> np.ndarray:
        """Process frame with tracking visualization"""
        
        # Resize for web display
        display_width = 640
        h, w = frame.shape[:2]
        if w > display_width:
            scale = display_width / w
            new_h = int(h * scale)
            frame = cv2.resize(frame, (display_width, new_h))
        
        # Vehicle tracking
        if self.vehicle_tracker:
            self.vehicle_tracker.update(frame, timestamp)
            frame = self.vehicle_tracker.draw_tracks(frame, show_ids=True)
        
        # Zone trigger
        if self.zone_trigger:
            result = self.zone_trigger.check_full(frame, timestamp)
            frame = self.zone_trigger.draw_zones(frame, result.fill_ratios, show_labels=True)
        
        # Overlay info
        cv2.putText(
            frame,
            f"{self.camera_id} | FPS: {self.fps:.1f}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
            cv2.LINE_AA
        )
        
        return frame
    
    def get_frame(self) -> Optional[np.ndarray]:
        """Get current frame (thread-safe)"""
        with self.lock:
            return self.frame.copy() if self.frame is not None else None


class CameraManager:
    """Manage multiple camera streams"""
    
    def __init__(self):
        self.streams: Dict[str, CameraStream] = {}
        self._load_cameras()
    
    def _load_cameras(self):
        """Load cameras from config"""
        try:
            cameras_json = os.getenv("CAMERAS_CONFIG", "[]")
            cameras = json.loads(cameras_json)
            
            for cam in cameras:
                camera_id = cam.get("id")
                rtsp_url = cam.get("rtsp")
                
                if camera_id and rtsp_url:
                    stream = CameraStream(camera_id, rtsp_url)
                    self.streams[camera_id] = stream
                    log.info(f"Loaded camera: {camera_id}")
        
        except Exception as e:
            log.error(f"Failed to load cameras: {e}")
    
    def start_all(self):
        """Start all camera streams"""
        for stream in self.streams.values():
            stream.start()
    
    def stop_all(self):
        """Stop all camera streams"""
        for stream in self.streams.values():
            stream.stop()
    
    def get_stream(self, camera_id: str) -> Optional[CameraStream]:
        """Get camera stream by ID"""
        return self.streams.get(camera_id)
    
    def list_cameras(self) -> List[Dict[str, str]]:
        """List all cameras"""
        return [
            {"id": cam_id, "name": cam_id}
            for cam_id in self.streams.keys()
        ]


# Global camera manager
camera_manager = CameraManager()


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Main dashboard page"""
    cameras = camera_manager.list_cameras()
    return render_template('dashboard.html', cameras=cameras)


@app.route('/api/cameras')
def api_cameras():
    """Get list of cameras"""
    return jsonify(camera_manager.list_cameras())


@app.route('/api/stats/<camera_id>')
def api_stats(camera_id):
    """Get camera stats from Redis"""
    try:
        key = f"rtsp:stats:{camera_id}"
        data = redis_client.hgetall(key)
        
        stats = {}
        for k, v in data.items():
            k_str = k.decode('utf-8') if isinstance(k, bytes) else k
            v_str = v.decode('utf-8') if isinstance(v, bytes) else v
            
            try:
                stats[k_str] = int(v_str)
            except ValueError:
                try:
                    stats[k_str] = float(v_str)
                except ValueError:
                    stats[k_str] = v_str
        
        return jsonify(stats)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/video_feed/<camera_id>')
def video_feed(camera_id):
    """MJPEG video stream"""
    stream = camera_manager.get_stream(camera_id)
    
    if stream is None:
        return "Camera not found", 404
    
    def generate():
        while True:
            frame = stream.get_frame()
            
            if frame is None:
                time.sleep(0.1)
                continue
            
            # Encode as JPEG
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if not ret:
                continue
            
            # Yield MJPEG frame
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            
            time.sleep(0.033)  # ~30 FPS
    
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/recent_captures')
def api_recent_captures():
    """Get recent captures from database"""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        engine = create_engine(config.database_url)
        Session = sessionmaker(bind=engine)
        db = Session()
        
        sql = text("""
            SELECT 
                id,
                camera_id,
                captured_at,
                original_path
            FROM captures
            ORDER BY captured_at DESC
            LIMIT :limit
        """)
        
        result = db.execute(sql, {"limit": limit})
        
        captures = []
        for row in result:
            captures.append({
                "id": row.id,
                "camera_id": row.camera_id,
                "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                "image_path": row.original_path,
            })
        
        db.close()
        
        return jsonify(captures)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# HTML Template
# ═══════════════════════════════════════════════════════════════

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ALPR Live Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0f0f19;
            color: #e2eaf4;
        }
        
        .header {
            background: #1a1a2e;
            padding: 20px;
            border-bottom: 2px solid #2e4060;
        }
        
        .header h1 {
            font-size: 24px;
            color: #3b82f6;
        }
        
        .container {
            padding: 20px;
            max-width: 1600px;
            margin: 0 auto;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(640px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .camera-card {
            background: #1a1a2e;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #2e4060;
        }
        
        .camera-video {
            width: 100%;
            height: auto;
            display: block;
        }
        
        .camera-info {
            padding: 15px;
            background: #0f0f19;
        }
        
        .camera-name {
            font-size: 18px;
            font-weight: 600;
            color: #3b82f6;
            margin-bottom: 10px;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }
        
        .stat-item {
            padding: 8px;
            background: #1a1a2e;
            border-radius: 4px;
            border: 1px solid #2e4060;
        }
        
        .stat-label {
            font-size: 12px;
            color: #9fb3cc;
            margin-bottom: 4px;
        }
        
        .stat-value {
            font-size: 20px;
            font-weight: 700;
            color: #e2eaf4;
        }
        
        .recent-captures {
            background: #1a1a2e;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #2e4060;
        }
        
        .recent-captures h2 {
            font-size: 20px;
            color: #3b82f6;
            margin-bottom: 15px;
        }
        
        .capture-list {
            list-style: none;
        }
        
        .capture-item {
            padding: 10px;
            border-bottom: 1px solid #2e4060;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .capture-item:last-child {
            border-bottom: none;
        }
        
        .capture-camera {
            font-weight: 600;
            color: #3b82f6;
        }
        
        .capture-time {
            font-size: 12px;
            color: #9fb3cc;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
            color: #9fb3cc;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚗 ALPR Live Dashboard</h1>
    </div>
    
    <div class="container">
        <div class="grid" id="camera-grid">
            {% for camera in cameras %}
            <div class="camera-card">
                <img 
                    src="/video_feed/{{ camera.id }}" 
                    alt="{{ camera.name }}"
                    class="camera-video"
                >
                <div class="camera-info">
                    <div class="camera-name">{{ camera.name }}</div>
                    <div class="stats" id="stats-{{ camera.id }}">
                        <div class="stat-item">
                            <div class="stat-label">Tracked</div>
                            <div class="stat-value">-</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">Captured</div>
                            <div class="stat-value">-</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">Frames Read</div>
                            <div class="stat-value">-</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">Enqueued</div>
                            <div class="stat-value">-</div>
                        </div>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <div class="recent-captures">
            <h2>📸 Recent Captures</h2>
            <ul class="capture-list" id="capture-list">
                <li class="loading">Loading...</li>
            </ul>
        </div>
    </div>
    
    <script>
        // Update stats every 2 seconds
        function updateStats() {
            {% for camera in cameras %}
            fetch('/api/stats/{{ camera.id }}')
                .then(r => r.json())
                .then(data => {
                    const container = document.getElementById('stats-{{ camera.id }}');
                    if (!container) return;
                    
                    const stats = container.querySelectorAll('.stat-value');
                    stats[0].textContent = data.vehicles_tracked || '0';
                    stats[1].textContent = data.vehicles_captured || '0';
                    stats[2].textContent = data.frames_read || '0';
                    stats[3].textContent = data.frames_enqueued || '0';
                })
                .catch(e => console.error('Failed to update stats:', e));
            {% endfor %}
        }
        
        // Update recent captures
        function updateCaptures() {
            fetch('/api/recent_captures?limit=10')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('capture-list');
                    if (!list) return;
                    
                    if (data.length === 0) {
                        list.innerHTML = '<li class="loading">No captures yet</li>';
                        return;
                    }
                    
                    list.innerHTML = data.map(cap => `
                        <li class="capture-item">
                            <div>
                                <span class="capture-camera">${cap.camera_id}</span>
                                <span class="capture-time">${new Date(cap.captured_at).toLocaleString()}</span>
                            </div>
                            <div>ID: ${cap.id}</div>
                        </li>
                    `).join('');
                })
                .catch(e => console.error('Failed to update captures:', e));
        }
        
        // Initial update
        updateStats();
        updateCaptures();
        
        // Auto-refresh
        setInterval(updateStats, 2000);
        setInterval(updateCaptures, 5000);
    </script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Create templates directory
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)
    
    # Write template
    with open(templates_dir / "dashboard.html", "w") as f:
        f.write(DASHBOARD_HTML)
    
    # Start camera streams
    log.info("Starting camera streams...")
    camera_manager.start_all()
    
    # Run Flask app
    log.info("Starting web dashboard on http://0.0.0.0:5000")
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    finally:
        camera_manager.stop_all()


if __name__ == '__main__':
    main()
