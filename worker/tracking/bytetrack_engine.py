# worker/tracking/bytetrack_engine.py
"""
LPR Tracking Engine with Trajectory-Based Line Crossing
Replaces zone-trigger logic with virtual line crossing detection
"""
import logging
import os
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Deque
import numpy as np
import cv2

log = logging.getLogger(__name__)


@dataclass
class Detection:
    """Vehicle Detection Result"""
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    score: float
    class_id: int
    
    @property
    def centroid(self) -> Tuple[int, int]:
        """Get centroid of bbox"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    
    @property
    def bottom_center(self) -> Tuple[int, int]:
        """Get bottom-center point (used for trajectory)"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, y2)
    
    @property
    def area(self) -> int:
        """Get bounding box area"""
        x1, y1, x2, y2 = self.bbox
        return max(0, (x2 - x1) * (y2 - y1))
    
    @property
    def tlwh(self) -> Tuple[int, int, int, int]:
        """Convert to top-left-width-height format"""
        x1, y1, x2, y2 = self.bbox
        return (x1, y1, x2 - x1, y2 - y1)


@dataclass
class TrackState:
    """Track State for Line Crossing Logic"""
    track_id: int
    bbox: Tuple[int, int, int, int]
    score: float
    class_id: int
    
    # Trajectory tracking
    trajectory: Deque[Tuple[int, int]] = field(default_factory=lambda: deque(maxlen=30))
    
    # Best crop buffering
    best_crop: Optional[np.ndarray] = None
    best_crop_area: int = 0
    
    # Line crossing state
    crossed_line: bool = False
    
    # Tracking metadata
    age: int = 0
    hits: int = 0
    time_since_update: int = 0


@dataclass
class LPRTriggerEvent:
    """Event triggered when vehicle crosses the line"""
    track_id: int
    count_id: int
    bbox: Tuple[int, int, int, int]
    vehicle_crop: np.ndarray
    score: float


class LPRTrackingEngine:
    """
    Trajectory-based tracking engine with virtual line crossing detection
    
    Features:
    - Multi-object tracking with ByteTrack
    - Trajectory history per track (bottom-center points)
    - Best crop buffering (largest/clearest frame)
    - Virtual line crossing detection using CCW intersection logic
    - One-time LPR trigger per track when crossing line
    """
    
    def __init__(
        self,
        count_line: List[Tuple[int, int]],
        track_thresh: float = 0.45,
        track_buffer: int = 30,
        match_thresh: float = 0.80,
        trajectory_maxlen: int = 30,
    ):
        """
        Initialize LPR Tracking Engine
        
        Args:
            count_line: Virtual line as [(x1, y1), (x2, y2)]
            track_thresh: Detection confidence threshold for tracking
            track_buffer: Number of frames to keep lost tracks
            match_thresh: IoU threshold for track matching
            trajectory_maxlen: Maximum trajectory points to store
        """
        if len(count_line) != 2:
            raise ValueError("count_line must have exactly 2 points: [(x1, y1), (x2, y2)]")
        
        self.count_line = count_line
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.trajectory_maxlen = trajectory_maxlen
        
        # Initialize ByteTrack
        try:
            from .bytetrack_impl import BYTETracker as ImplBYTETracker
            self.tracker = ImplBYTETracker(
                track_thresh=track_thresh,
                track_buffer=track_buffer,
                match_thresh=match_thresh,
                frame_rate=30
            )
            log.info("ByteTrack initialized (thresh=%.2f, buffer=%d)", track_thresh, track_buffer)
        except ImportError:
            self.tracker = BYTETracker(
                track_thresh=track_thresh,
                track_buffer=track_buffer,
                match_thresh=match_thresh,
                frame_rate=30
            )
            log.warning("ByteTrack package not found; using simplified built-in tracker fallback")
        
        # Track states
        self.track_states: Dict[int, TrackState] = {}
        
        # Vehicle count
        self.vehicle_count = 0
        
        log.info(
            "LPRTrackingEngine initialized: count_line=%s, trajectory_maxlen=%d",
            count_line, trajectory_maxlen
        )
    
    def update(
        self,
        detections: List[Detection],
        frame: np.ndarray,
    ) -> Tuple[List[LPRTriggerEvent], int]:
        """
        Update tracker with new detections and check line crossings
        
        Args:
            detections: List of vehicle detections
            frame: Current frame (BGR image)
        
        Returns:
            Tuple of (trigger_ocr_list, vehicle_count)
            - trigger_ocr_list: List of LPRTriggerEvent for vehicles that crossed the line
            - vehicle_count: Total count of vehicles that crossed
        """
        trigger_ocr_list: List[LPRTriggerEvent] = []
        
        # Convert detections to ByteTrack format
        if len(detections) == 0:
            online_tracks = self.tracker.update(np.empty((0, 5)))
        else:
            det_array = np.array([
                [*d.bbox, d.score] for d in detections
            ], dtype=np.float32)
            online_tracks = self.tracker.update(det_array)
        
        # Process tracks
        current_track_ids = set()
        
        for track in online_tracks:
            track_id = int(track.track_id)
            current_track_ids.add(track_id)
            
            # Get or create track state
            if track_id not in self.track_states:
                self.track_states[track_id] = TrackState(
                    track_id=track_id,
                    bbox=tuple(map(int, track.tlbr)),
                    score=float(track.score),
                    class_id=0,
                )
                log.debug("New track created: track_id=%d", track_id)
            
            state = self.track_states[track_id]
            
            # Update state
            bbox = tuple(map(int, track.tlbr))
            state.bbox = bbox
            state.score = float(track.score)
            state.age += 1
            state.hits = int(track.hit_streak)
            state.time_since_update = 0
            
            # Update trajectory (bottom-center point)
            x1, y1, x2, y2 = bbox
            bottom_center = ((x1 + x2) // 2, y2)
            state.trajectory.append(bottom_center)
            
            # Update best crop (largest area)
            try:
                x1 = max(0, min(x1, frame.shape[1] - 1))
                y1 = max(0, min(y1, frame.shape[0] - 1))
                x2 = max(0, min(x2, frame.shape[1]))
                y2 = max(0, min(y2, frame.shape[0]))
                
                if x2 > x1 and y2 > y1:
                    crop = frame[y1:y2, x1:x2].copy()
                    crop_area = (x2 - x1) * (y2 - y1)
                    
                    if crop_area > state.best_crop_area:
                        state.best_crop = crop
                        state.best_crop_area = crop_area
                        log.debug(
                            "Updated best crop for track_id=%d: area=%d",
                            track_id, crop_area
                        )
            except Exception as e:
                log.warning("Failed to extract crop for track_id=%d: %s", track_id, e)
            
            # Check line crossing (only if not already crossed)
            if not state.crossed_line and len(state.trajectory) >= 2:
                # Check if trajectory crossed the count line
                if self._check_trajectory_crossing(state.trajectory):
                    state.crossed_line = True
                    self.vehicle_count += 1
                    
                    log.info(
                        "🚗 LINE CROSSED: track_id=%d, count=%d, bbox=%s",
                        track_id, self.vehicle_count, bbox
                    )
                    
                    # Create trigger event
                    if state.best_crop is not None:
                        event = LPRTriggerEvent(
                            track_id=track_id,
                            count_id=self.vehicle_count,
                            bbox=bbox,
                            vehicle_crop=state.best_crop,
                            score=state.score,
                        )
                        trigger_ocr_list.append(event)
                    else:
                        log.warning(
                            "Track %d crossed line but has no best_crop. Skipping LPR.",
                            track_id
                        )
        
        # Cleanup stale tracks
        stale_track_ids = []
        for track_id in list(self.track_states.keys()):
            if track_id not in current_track_ids:
                state = self.track_states[track_id]
                state.time_since_update += 1
                
                # Remove after buffer timeout
                if state.time_since_update > self.track_buffer:
                    stale_track_ids.append(track_id)
        
        for track_id in stale_track_ids:
            del self.track_states[track_id]
            log.debug("Track %d removed (timeout)", track_id)
        
        return trigger_ocr_list, self.vehicle_count
    
    def _check_trajectory_crossing(self, trajectory: Deque[Tuple[int, int]]) -> bool:
        """
        Check if trajectory crossed the count line using segment intersection
        
        Args:
            trajectory: Deque of (x, y) bottom-center points
        
        Returns:
            True if any segment in trajectory intersects the count line
        """
        if len(trajectory) < 2:
            return False
        
        line_A, line_B = self.count_line
        
        # Check last segment against count line
        for i in range(len(trajectory) - 1):
            pt_C = trajectory[i]
            pt_D = trajectory[i + 1]
            
            if self._check_intersect(line_A, line_B, pt_C, pt_D):
                return True
        
        return False
    
    @staticmethod
    def _check_intersect(
        A: Tuple[int, int],
        B: Tuple[int, int],
        C: Tuple[int, int],
        D: Tuple[int, int],
    ) -> bool:
        """
        Check if line segment AB intersects line segment CD using CCW logic
        
        Args:
            A, B: Endpoints of first line segment (count line)
            C, D: Endpoints of second line segment (trajectory segment)
        
        Returns:
            True if segments intersect
        """
        def ccw(A, B, C):
            """Counter-clockwise orientation test"""
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
        
        # Two segments intersect if endpoints are on opposite sides
        return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)
    
    def get_stats(self) -> Dict:
        """Get tracking statistics"""
        return {
            "active_tracks": len(self.track_states),
            "vehicle_count": self.vehicle_count,
            "crossed_tracks": sum(1 for s in self.track_states.values() if s.crossed_line),
        }
    
    def reset_count(self):
        """Reset vehicle count (useful for testing or daily resets)"""
        self.vehicle_count = 0
        log.info("Vehicle count reset to 0")


# ===================== ByteTrack Implementation (Minimal Fallback) =====================

class STrack:
    """Single Track (simplified)"""
    def __init__(self, tlwh, score, track_id):
        self.tlwh = np.array(tlwh, dtype=np.float32)
        self.score = score
        self.track_id = track_id
        self.hit_streak = 1
        self.age = 1
        self.time_since_update = 0
    
    @property
    def tlbr(self):
        """Convert tlwh to tlbr"""
        ret = self.tlwh.copy()
        ret[2:] += ret[:2]
        return ret


class BYTETracker:
    """ByteTrack implementation (simplified fallback)"""
    def __init__(self, track_thresh=0.45, track_buffer=30, match_thresh=0.80, frame_rate=30):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.iou_match_thresh = float(os.getenv("FALLBACK_TRACK_IOU_THRESH", "0.30"))
        self.frame_rate = frame_rate
        
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []
        
        self.frame_id = 0
        self.track_id_count = 0
    
    def update(self, dets):
        """Update tracks with new detections"""
        self.frame_id += 1

        # Age tracks
        for track in self.tracked_stracks:
            track.age += 1
            track.time_since_update += 1

        if len(dets) == 0:
            self._prune_stale_tracks()
            return []

        # Filter detections by threshold
        dets = [det for det in dets if det[4] >= self.track_thresh]
        if len(dets) == 0:
            self._prune_stale_tracks()
            return []

        # Greedy IoU matching
        unmatched_tracks = set(range(len(self.tracked_stracks)))
        unmatched_dets = set(range(len(dets)))
        matches = []

        while unmatched_tracks and unmatched_dets:
            best_pair = None
            best_iou = 0.0
            for t_idx in unmatched_tracks:
                t_tlbr = self.tracked_stracks[t_idx].tlbr
                for d_idx in unmatched_dets:
                    d_tlbr = dets[d_idx][:4]
                    iou = self._iou(t_tlbr, d_tlbr)
                    if iou > best_iou:
                        best_iou = iou
                        best_pair = (t_idx, d_idx)

            if best_pair is None or best_iou < self.iou_match_thresh:
                break

            t_idx, d_idx = best_pair
            matches.append((t_idx, d_idx))
            unmatched_tracks.discard(t_idx)
            unmatched_dets.discard(d_idx)

        active_tracks = []

        # Update matched tracks
        for t_idx, d_idx in matches:
            track = self.tracked_stracks[t_idx]
            x1, y1, x2, y2, score = dets[d_idx]
            track.tlwh = np.array([x1, y1, x2 - x1, y2 - y1], dtype=np.float32)
            track.score = float(score)
            track.hit_streak += 1
            track.time_since_update = 0
            active_tracks.append(track)

        # Create new tracks for unmatched detections
        for d_idx in unmatched_dets:
            x1, y1, x2, y2, score = dets[d_idx]
            self.track_id_count += 1
            track = STrack([x1, y1, x2 - x1, y2 - y1], float(score), self.track_id_count)
            active_tracks.append(track)

        # Keep unmatched old tracks alive until buffer timeout
        survivors = [
            self.tracked_stracks[t_idx]
            for t_idx in unmatched_tracks
            if self.tracked_stracks[t_idx].time_since_update <= self.track_buffer
        ]
        self.tracked_stracks = active_tracks + survivors
        self._prune_stale_tracks()
        return active_tracks

    def _prune_stale_tracks(self):
        """Remove tracks that exceeded buffer timeout"""
        self.tracked_stracks = [
            t for t in self.tracked_stracks if t.time_since_update <= self.track_buffer
        ]

    @staticmethod
    def _iou(a, b):
        """Calculate IoU between two bboxes in tlbr format"""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1.0, (bx2 - bx1) * (by2 - by1))
        return float(inter / (area_a + area_b - inter))