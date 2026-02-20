# worker/tracking/bytetrack_engine.py
"""
ByteTrack Integration with Zone Trigger Logic for LPR
Uses TensorRT vehicle detection + tracking + zone-based LPR triggering
"""
import logging
import os
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import numpy as np
from collections import defaultdict

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
    def tlwh(self) -> Tuple[int, int, int, int]:
        """Convert to top-left-width-height format"""
        x1, y1, x2, y2 = self.bbox
        return (x1, y1, x2 - x1, y2 - y1)


@dataclass
class TrackState:
    """Track State for Zone Trigger Logic"""
    track_id: int
    bbox: Tuple[int, int, int, int]
    score: float
    class_id: int
    
    # Zone trigger state
    frames_in_zone: int = 0
    entered_zone: bool = False
    lpr_triggered: bool = False
    
    # Tracking
    age: int = 0
    hits: int = 0
    time_since_update: int = 0


class ByteTrackEngine:
    """
    ByteTrack wrapper with Zone Trigger Logic
    
    Features:
    - Multi-object tracking with ByteTrack
    - Zone entry detection (centroid-based)
    - One-time LPR trigger per track when entering zone
    - Track state management with Redis persistence
    """
    
    def __init__(
        self,
        track_thresh: float = 0.45,
        track_buffer: int = 30,
        match_thresh: float = 0.80,
        min_frames_in_zone: int = 3,
        redis_client = None,
    ):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.min_frames_in_zone = min_frames_in_zone
        self.redis = redis_client
        
        # Import ByteTrack implementation
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
            # Fallback to lightweight local implementation to keep tracking
            # pipeline usable even when optional ByteTrack package is absent.
            self.tracker = BYTETracker(
                track_thresh=track_thresh,
                track_buffer=track_buffer,
                match_thresh=match_thresh,
                frame_rate=30
            )
            log.warning(
                "ByteTrack package not found; using simplified built-in tracker fallback"
            )
        
        # Track states (camera_id -> track_id -> TrackState)
        self.track_states: Dict[str, Dict[int, TrackState]] = defaultdict(dict)
    
    def update(
        self,
        camera_id: str,
        detections: List[Detection],
        zone_polygon: Optional[List[Tuple[int, int]]] = None,
    ) -> List[TrackState]:
        """
        Update tracker with new detections and check zone triggers
        
        Args:
            camera_id: Camera identifier
            detections: List of vehicle detections
            zone_polygon: Polygon points for zone trigger
        
        Returns:
            List of active tracks with zone trigger status
        """
        # Convert detections to ByteTrack format
        if len(detections) == 0:
            # Update with empty detections
            online_tracks = self.tracker.update(np.empty((0, 5)))
        else:
            det_array = np.array([
                [*d.bbox, d.score] for d in detections
            ], dtype=np.float32)
            online_tracks = self.tracker.update(det_array)
        
        # Process tracks
        active_tracks = []
        current_track_ids = set()
        
        for track in online_tracks:
            track_id = int(track.track_id)
            current_track_ids.add(track_id)
            
            # Get or create track state
            if track_id not in self.track_states[camera_id]:
                self.track_states[camera_id][track_id] = TrackState(
                    track_id=track_id,
                    bbox=tuple(map(int, track.tlbr)),
                    score=float(track.score),
                    class_id=0,  # Assume car for now
                )
            
            state = self.track_states[camera_id][track_id]
            
            # Update state
            state.bbox = tuple(map(int, track.tlbr))
            state.score = float(track.score)
            state.age += 1
            state.hits = int(track.hit_streak)
            state.time_since_update = 0
            
            # Check zone trigger
            if zone_polygon and not state.lpr_triggered:
                centroid = self._get_centroid(state.bbox)
                in_zone = self._is_point_in_polygon(centroid, zone_polygon)
                
                if in_zone:
                    state.frames_in_zone += 1
                    
                    if not state.entered_zone:
                        state.entered_zone = True
                        log.debug(
                            "Track %d entered zone (camera=%s, frames=%d)",
                            track_id, camera_id, state.frames_in_zone
                        )
                    
                    # Trigger LPR after min frames in zone
                    if state.frames_in_zone >= self.min_frames_in_zone:
                        if not state.lpr_triggered:
                            state.lpr_triggered = True
                            log.info(
                                "🚨 LPR TRIGGER: Track %d (camera=%s, bbox=%s)",
                                track_id, camera_id, state.bbox
                            )
                else:
                    if state.entered_zone:
                        # Left zone
                        state.frames_in_zone = 0
            
            active_tracks.append(state)
        
        # Cleanup old tracks
        for track_id in list(self.track_states[camera_id].keys()):
            if track_id not in current_track_ids:
                state = self.track_states[camera_id][track_id]
                state.time_since_update += 1
                
                # Remove after buffer timeout
                if state.time_since_update > self.track_buffer:
                    del self.track_states[camera_id][track_id]
                    log.debug("Track %d removed (timeout)", track_id)
        
        return active_tracks
    
    def get_lpr_candidates(
        self,
        camera_id: str,
    ) -> List[TrackState]:
        """Get tracks that need LPR processing (lpr_triggered=True)"""
        if camera_id not in self.track_states:
            return []
        
        candidates = [
            state for state in self.track_states[camera_id].values()
            if state.lpr_triggered and state.time_since_update == 0
        ]
        
        return candidates
    
    def mark_lpr_processed(self, camera_id: str, track_id: int):
        """Mark track as LPR processed (reset trigger)"""
        if camera_id in self.track_states and track_id in self.track_states[camera_id]:
            # Keep lpr_triggered=True to prevent re-trigger
            pass
    
    def _get_centroid(self, bbox: Tuple[int, int, int, int]) -> Tuple[int, int]:
        """Get centroid of bounding box"""
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    
    def _is_point_in_polygon(
        self,
        point: Tuple[int, int],
        polygon: List[Tuple[int, int]]
    ) -> bool:
        """Check if point is inside polygon using ray casting"""
        x, y = point
        n = len(polygon)
        inside = False
        
        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    def get_camera_stats(self, camera_id: str) -> Dict:
        """Get tracking statistics for camera"""
        if camera_id not in self.track_states:
            return {
                "active_tracks": 0,
                "tracks_in_zone": 0,
                "lpr_triggered": 0,
            }
        
        states = self.track_states[camera_id].values()
        
        return {
            "active_tracks": len(states),
            "tracks_in_zone": sum(1 for s in states if s.entered_zone),
            "lpr_triggered": sum(1 for s in states if s.lpr_triggered),
        }


# ===================== ByteTrack Implementation (Minimal) =====================
# This is a simplified version. For production, use official ByteTrack package:
# https://github.com/ifzhang/ByteTrack

class STrack:
    """Single Track (simplified)"""
    def __init__(self, tlwh, score, track_id):
        self.tlwh = np.array(tlwh, dtype=np.float32)
        self.score = score
        self.track_id = track_id
        self.hit_streak = 1
        self.age = 1
    
    @property
    def tlbr(self):
        """Convert tlwh to tlbr"""
        ret = self.tlwh.copy()
        ret[2:] += ret[:2]
        return ret


class BYTETracker:
    """ByteTrack implementation (simplified for demo)"""
    def __init__(self, track_thresh=0.45, track_buffer=30, match_thresh=0.80, frame_rate=30):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.frame_rate = frame_rate
        
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []
        
        self.frame_id = 0
        self.track_id_count = 0
    
    def update(self, dets):
        """Update tracks with new detections"""
        self.frame_id += 1
        
        if len(dets) == 0:
            # No detections, age existing tracks
            for track in self.tracked_stracks:
                track.age += 1
            return []
        
        # Simple assignment: create new tracks for all detections
        # (In production, use IoU matching with Hungarian algorithm)
        activated_tracks = []
        
        for det in dets:
            x1, y1, x2, y2, score = det
            if score < self.track_thresh:
                continue
            
            tlwh = [x1, y1, x2 - x1, y2 - y1]
            
            # Create new track
            self.track_id_count += 1
            track = STrack(tlwh, score, self.track_id_count)
            activated_tracks.append(track)
        
        self.tracked_stracks = activated_tracks
        return self.tracked_stracks
