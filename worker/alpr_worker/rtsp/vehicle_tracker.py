"""
vehicle_tracker.py — Vehicle Tracking for ALPR System
======================================================

Track vehicles across frames to ensure each vehicle is captured only once.

Features:
- Lightweight tracking using motion + ROI overlap
- Assign unique tracking ID to each vehicle
- Track vehicle state (new/active/captured/gone)
- Cooldown per tracking ID to avoid duplicate captures
- Memory-efficient (no deep learning, uses detection boxes only)

Algorithm:
1. Detect motion blobs in frame
2. Match current detections to existing tracks using IoU + position
3. Assign new track ID if no match found
4. Track state transitions: NEW → ACTIVE → CAPTURED → EXPIRED
5. Only trigger capture once per track ID

ENV:
  VEHICLE_TRACKING_ENABLED=true
  VEHICLE_TRACKING_MAX_AGE=30              # frames before track expires
  VEHICLE_TRACKING_MIN_HITS=3              # min detections before considered stable
  VEHICLE_TRACKING_IOU_THRESHOLD=0.3       # IoU threshold for matching
  VEHICLE_TRACKING_CAPTURE_COOLDOWN=15.0   # seconds between captures per track
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ─── Data Classes ────────────────────────────────────────────


@dataclass
class Detection:
    """Single detection (motion blob) in a frame"""
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float = 1.0
    timestamp: float = 0.0


@dataclass
class VehicleTrack:
    """
    Tracking state for a single vehicle
    
    States:
        NEW: Just detected, not stable yet
        ACTIVE: Stable track (seen multiple times)
        CAPTURED: Already captured this vehicle
        EXPIRED: Track lost (vehicle left frame)
    """
    track_id: int
    bbox: Tuple[int, int, int, int]  # current position (x1,y1,x2,y2)
    state: str = "NEW"  # NEW | ACTIVE | CAPTURED | EXPIRED
    
    # Tracking metadata
    hits: int = 1                    # number of times detected
    age: int = 0                     # frames since created
    time_since_update: int = 0       # frames since last matched
    
    # Capture tracking
    first_seen: float = 0.0          # timestamp when first detected
    last_seen: float = 0.0           # timestamp when last matched
    captured_at: float = 0.0         # timestamp when captured
    
    # History for velocity estimation
    positions: List[Tuple[int, int]] = field(default_factory=list)  # (cx, cy) history
    
    def update(self, detection: Detection, timestamp: float):
        """Update track with new detection"""
        self.bbox = detection.bbox
        self.hits += 1
        self.time_since_update = 0
        self.last_seen = timestamp
        
        # Update position history (keep last 10)
        cx = (detection.bbox[0] + detection.bbox[2]) // 2
        cy = (detection.bbox[1] + detection.bbox[3]) // 2
        self.positions.append((cx, cy))
        if len(self.positions) > 10:
            self.positions.pop(0)
    
    def mark_missed(self):
        """Mark that this track wasn't matched in current frame"""
        self.time_since_update += 1
        self.age += 1
    
    def mark_captured(self, timestamp: float):
        """Mark this track as captured"""
        self.state = "CAPTURED"
        self.captured_at = timestamp
    
    @property
    def is_stable(self) -> bool:
        """Track is stable if seen multiple times"""
        return self.hits >= 3 and self.state == "ACTIVE"
    
    @property
    def center(self) -> Tuple[int, int]:
        """Current center position"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    
    @property
    def area(self) -> int:
        """Current bbox area"""
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)
    
    def get_velocity(self) -> Tuple[float, float]:
        """Estimate velocity from position history (pixels/frame)"""
        if len(self.positions) < 2:
            return (0.0, 0.0)
        
        # Use last 5 positions for velocity
        recent = self.positions[-5:]
        dx = recent[-1][0] - recent[0][0]
        dy = recent[-1][1] - recent[0][1]
        frames = len(recent) - 1
        
        return (dx / frames, dy / frames)


@dataclass
class TrackingResult:
    """Result from tracker.update()"""
    active_tracks: List[VehicleTrack]
    new_tracks: List[VehicleTrack]
    ready_to_capture: List[VehicleTrack]  # tracks ready for capture
    total_tracks: int


# ─── Helper Functions ────────────────────────────────────────


def compute_iou(box1: Tuple[int, int, int, int], 
                box2: Tuple[int, int, int, int]) -> float:
    """Compute IoU (Intersection over Union) between two boxes"""
    x1_1, y1_1, x2_1, y2_1 = box1
    x1_2, y1_2, x2_2, y2_2 = box2
    
    # Intersection
    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    
    if x2_i < x1_i or y2_i < y1_i:
        return 0.0
    
    inter_area = (x2_i - x1_i) * (y2_i - y1_i)
    
    # Union
    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
    union_area = area1 + area2 - inter_area
    
    if union_area == 0:
        return 0.0
    
    return inter_area / union_area


def detect_motion_blobs(frame: np.ndarray, 
                        prev_frame: Optional[np.ndarray],
                        min_area: int = 1500) -> List[Detection]:
    """
    Detect motion blobs using frame differencing
    
    Returns list of Detection objects (bounding boxes)
    """
    if prev_frame is None or prev_frame.shape != frame.shape:
        return []
    
    # Convert to grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    prev_gray = cv2.GaussianBlur(prev_gray, (21, 21), 0)
    
    # Frame difference
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    
    # Morphological operations to clean up
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    thresh = cv2.dilate(thresh, kernel, iterations=2)
    thresh = cv2.erode(thresh, kernel, iterations=1)
    
    # Find contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detections = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        
        x, y, w, h = cv2.boundingRect(contour)
        bbox = (x, y, x + w, y + h)
        detections.append(Detection(bbox=bbox, timestamp=time.time()))
    
    return detections


# ─── Main Tracker Class ──────────────────────────────────────


class VehicleTracker:
    """
    Track vehicles across frames to ensure single capture per vehicle
    
    Usage:
        tracker = VehicleTracker()
        
        while True:
            ret, frame = cap.read()
            result = tracker.update(frame, time.time())
            
            for track in result.ready_to_capture:
                if not tracker.was_captured(track.track_id):
                    # Capture this vehicle
                    save_and_enqueue(frame)
                    tracker.mark_captured(track.track_id, time.time())
    """
    
    def __init__(self,
                 max_age: int = 30,
                 min_hits: int = 3,
                 iou_threshold: float = 0.3,
                 capture_cooldown: float = 15.0):
        """
        Args:
            max_age: Max frames to keep track without detection
            min_hits: Min detections before track is stable
            iou_threshold: IoU threshold for matching detection to track
            capture_cooldown: Seconds between captures for same track ID
        """
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.capture_cooldown = capture_cooldown
        
        self._next_id = 1
        self._tracks: Dict[int, VehicleTrack] = {}
        self._captured_tracks: Dict[int, float] = {}  # {track_id: timestamp}
        self._prev_frame: Optional[np.ndarray] = None
        
        log.info(
            "VehicleTracker: max_age=%d min_hits=%d iou_threshold=%.2f cooldown=%.1fs",
            max_age, min_hits, iou_threshold, capture_cooldown
        )
    
    def update(self, frame: np.ndarray, timestamp: float) -> TrackingResult:
        """
        Update tracker with new frame
        
        Args:
            frame: Current BGR frame
            timestamp: Current timestamp (seconds)
        
        Returns:
            TrackingResult with active tracks and ready-to-capture list
        """
        # Detect motion blobs
        detections = detect_motion_blobs(frame, self._prev_frame)
        self._prev_frame = frame.copy()
        
        # Match detections to existing tracks
        matched_tracks, unmatched_detections = self._match_detections(
            detections, timestamp
        )
        
        # Create new tracks for unmatched detections
        new_tracks = []
        for det in unmatched_detections:
            track = VehicleTrack(
                track_id=self._next_id,
                bbox=det.bbox,
                state="NEW",
                first_seen=timestamp,
                last_seen=timestamp,
            )
            self._tracks[self._next_id] = track
            new_tracks.append(track)
            self._next_id += 1
            log.debug("New track created: ID=%d", track.track_id)
        
        # Update track states
        for track in self._tracks.values():
            if track.track_id in matched_tracks:
                # Matched track
                if track.state == "NEW" and track.hits >= self.min_hits:
                    track.state = "ACTIVE"
                    log.info("Track %d promoted to ACTIVE", track.track_id)
            else:
                # Missed track
                track.mark_missed()
                
                # Expire old tracks
                if track.time_since_update > self.max_age:
                    track.state = "EXPIRED"
        
        # Remove expired tracks
        expired = [tid for tid, t in self._tracks.items() if t.state == "EXPIRED"]
        for tid in expired:
            log.debug("Track %d expired", tid)
            del self._tracks[tid]
        
        # Find tracks ready to capture
        ready_to_capture = self._get_ready_tracks(timestamp)
        
        return TrackingResult(
            active_tracks=[t for t in self._tracks.values() if t.state == "ACTIVE"],
            new_tracks=new_tracks,
            ready_to_capture=ready_to_capture,
            total_tracks=len(self._tracks),
        )
    
    def _match_detections(
        self, 
        detections: List[Detection],
        timestamp: float
    ) -> Tuple[set, List[Detection]]:
        """
        Match detections to existing tracks using Hungarian algorithm (simplified)
        
        Returns:
            (matched_track_ids, unmatched_detections)
        """
        if not detections or not self._tracks:
            return (set(), detections)
        
        # Compute cost matrix (1 - IoU)
        active_tracks = [t for t in self._tracks.values() if t.state != "EXPIRED"]
        
        if not active_tracks:
            return (set(), detections)
        
        cost_matrix = np.zeros((len(detections), len(active_tracks)))
        
        for i, det in enumerate(detections):
            for j, track in enumerate(active_tracks):
                iou = compute_iou(det.bbox, track.bbox)
                cost_matrix[i, j] = 1.0 - iou
        
        # Simple greedy matching (for production, use scipy.optimize.linear_sum_assignment)
        matched_tracks = set()
        unmatched_detections = []
        used_detections = set()
        
        for j, track in enumerate(active_tracks):
            # Find best detection for this track
            best_i = -1
            best_iou = 0.0
            
            for i in range(len(detections)):
                if i in used_detections:
                    continue
                
                iou = 1.0 - cost_matrix[i, j]
                if iou > best_iou and iou >= self.iou_threshold:
                    best_iou = iou
                    best_i = i
            
            if best_i >= 0:
                # Match found
                track.update(detections[best_i], timestamp)
                matched_tracks.add(track.track_id)
                used_detections.add(best_i)
        
        # Collect unmatched detections
        for i, det in enumerate(detections):
            if i not in used_detections:
                unmatched_detections.append(det)
        
        return (matched_tracks, unmatched_detections)
    
    def _get_ready_tracks(self, timestamp: float) -> List[VehicleTrack]:
        """
        Get tracks that are ready to capture
        
        Criteria:
        - Track is ACTIVE (stable)
        - Not yet captured, OR cooldown period passed
        """
        ready = []
        
        for track in self._tracks.values():
            if track.state != "ACTIVE":
                continue
            
            # Check if already captured
            if track.track_id in self._captured_tracks:
                last_capture = self._captured_tracks[track.track_id]
                if (timestamp - last_capture) < self.capture_cooldown:
                    continue  # Still in cooldown
            
            ready.append(track)
        
        return ready
    
    def mark_captured(self, track_id: int, timestamp: float):
        """Mark that a track has been captured"""
        if track_id in self._tracks:
            self._tracks[track_id].mark_captured(timestamp)
        
        self._captured_tracks[track_id] = timestamp
        log.info("Track %d marked as captured", track_id)
    
    def was_captured(self, track_id: int, timestamp: Optional[float] = None) -> bool:
        """Check if track was recently captured"""
        if track_id not in self._captured_tracks:
            return False
        
        if timestamp is None:
            return True
        
        last_capture = self._captured_tracks[track_id]
        return (timestamp - last_capture) < self.capture_cooldown
    
    def get_track(self, track_id: int) -> Optional[VehicleTrack]:
        """Get track by ID"""
        return self._tracks.get(track_id)
    
    def draw_tracks(self, frame: np.ndarray, show_ids: bool = True) -> np.ndarray:
        """
        Draw tracks on frame for debugging
        
        Args:
            frame: BGR frame
            show_ids: Show track IDs and state
        
        Returns:
            Frame with tracks drawn
        """
        out = frame.copy()
        
        for track in self._tracks.values():
            # Color by state
            if track.state == "NEW":
                color = (255, 255, 0)  # Cyan
            elif track.state == "ACTIVE":
                color = (0, 255, 0)    # Green
            elif track.state == "CAPTURED":
                color = (0, 165, 255)  # Orange
            else:
                color = (128, 128, 128)  # Gray
            
            # Draw bbox
            x1, y1, x2, y2 = track.bbox
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            
            # Draw ID and state
            if show_ids:
                label = f"ID:{track.track_id} {track.state}"
                if track.track_id in self._captured_tracks:
                    label += " ✓"
                
                cv2.putText(
                    out, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA
                )
            
            # Draw velocity arrow
            vx, vy = track.get_velocity()
            if abs(vx) > 1 or abs(vy) > 1:
                cx, cy = track.center
                cv2.arrowedLine(
                    out, 
                    (cx, cy), 
                    (int(cx + vx * 5), int(cy + vy * 5)),
                    color, 2
                )
        
        # Stats overlay
        active_count = sum(1 for t in self._tracks.values() if t.state == "ACTIVE")
        captured_count = len(self._captured_tracks)
        
        cv2.putText(
            out, 
            f"Tracks: {active_count} active | {captured_count} captured", 
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA
        )
        
        return out
    
    def reset(self):
        """Reset tracker state (call on stream reconnect)"""
        self._tracks.clear()
        self._captured_tracks.clear()
        self._prev_frame = None
        log.info("VehicleTracker reset")


# ─── Factory ──────────────────────────────────────────────────


def create_tracker_from_env() -> Optional[VehicleTracker]:
    """Create tracker from ENV variables"""
    import os
    
    enabled = os.getenv("VEHICLE_TRACKING_ENABLED", "false").lower() == "true"
    if not enabled:
        return None
    
    max_age = int(os.getenv("VEHICLE_TRACKING_MAX_AGE", "30"))
    min_hits = int(os.getenv("VEHICLE_TRACKING_MIN_HITS", "3"))
    iou_threshold = float(os.getenv("VEHICLE_TRACKING_IOU_THRESHOLD", "0.3"))
    cooldown = float(os.getenv("VEHICLE_TRACKING_CAPTURE_COOLDOWN", "15.0"))
    
    return VehicleTracker(
        max_age=max_age,
        min_hits=min_hits,
        iou_threshold=iou_threshold,
        capture_cooldown=cooldown,
    )


# ─── Self Test ────────────────────────────────────────────────


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s"
    )
    
    print("=" * 60)
    print("VehicleTracker Self-Test")
    print("=" * 60)
    print()
    
    # Test 1: IoU computation
    print("[1] IoU computation")
    box1 = (100, 100, 200, 200)
    box2 = (150, 150, 250, 250)
    iou = compute_iou(box1, box2)
    assert 0.1 < iou < 0.3, f"Expected IoU ~0.14, got {iou}"
    print(f"  ✅ IoU({box1}, {box2}) = {iou:.3f}")
    
    # Test 2: Track creation and update
    print("\n[2] Track creation and update")
    tracker = VehicleTracker(max_age=10, min_hits=3, iou_threshold=0.3)
    
    # Simulate moving vehicle
    frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
    frame2 = frame1.copy()
    frame2[100:200, 100:200] = 200  # Add motion
    
    result1 = tracker.update(frame1, 0.0)
    result2 = tracker.update(frame2, 0.1)
    
    assert result2.total_tracks >= 1, "Should have created at least 1 track"
    print(f"  ✅ Created {result2.total_tracks} tracks")
    
    # Test 3: Track state transitions
    print("\n[3] Track state transitions")
    
    # Repeat detection to promote to ACTIVE
    for i in range(5):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[100:200, 100 + i*10:200 + i*10] = 200  # Moving vehicle
        result = tracker.update(frame, 0.2 + i * 0.1)
    
    active_tracks = [t for t in tracker._tracks.values() if t.state == "ACTIVE"]
    assert len(active_tracks) >= 1, "Should have active tracks"
    print(f"  ✅ {len(active_tracks)} tracks promoted to ACTIVE")
    
    # Test 4: Capture tracking
    print("\n[4] Capture tracking")
    if active_tracks:
        track = active_tracks[0]
        tracker.mark_captured(track.track_id, 1.0)
        assert tracker.was_captured(track.track_id, 1.0)
        assert not tracker.was_captured(track.track_id, 20.0)  # After cooldown
        print(f"  ✅ Track {track.track_id} capture tracking works")
    
    # Test 5: Draw tracks
    print("\n[5] Draw tracks visualization")
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    drawn = tracker.draw_tracks(test_frame, show_ids=True)
    assert drawn.shape == test_frame.shape
    assert not np.array_equal(drawn, test_frame)  # Should have drawn something
    print(f"  ✅ draw_tracks() works")
    
    print("\n" + "=" * 60)
    print("✅ All VehicleTracker tests passed!")
    print("=" * 60)