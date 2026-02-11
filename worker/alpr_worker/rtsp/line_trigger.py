"""
Virtual line trigger for RTSP frame capture.

This module detects motion blobs and fires only when the blob centroid
crosses a configured virtual line (tripwire).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Literal

import cv2
import numpy as np


Direction = Literal["both", "up", "down", "left", "right"]


@dataclass
class LineTriggerConfig:
    enabled: bool = False
    x1: float = 0.10
    y1: float = 0.55
    x2: float = 0.90
    y2: float = 0.55
    direction: Direction = "both"
    band_px: int = 36
    min_area_px: int = 1800
    cooldown_sec: float = 1.5

    def __post_init__(self):
        self.x1 = max(0.0, min(self.x1, 1.0))
        self.y1 = max(0.0, min(self.y1, 1.0))
        self.x2 = max(0.0, min(self.x2, 1.0))
        self.y2 = max(0.0, min(self.y2, 1.0))
        self.band_px = max(4, int(self.band_px))
        self.min_area_px = max(50, int(self.min_area_px))
        self.cooldown_sec = max(0.0, float(self.cooldown_sec))
        if self.direction not in {"both", "up", "down", "left", "right"}:
            self.direction = "both"

    @classmethod
    def from_env(cls, prefix: str = "RTSP_LINE") -> "LineTriggerConfig":
        return cls(
            enabled=os.getenv(f"{prefix}_ENABLED", "false").lower() == "true",
            x1=float(os.getenv(f"{prefix}_X1", "0.10")),
            y1=float(os.getenv(f"{prefix}_Y1", "0.55")),
            x2=float(os.getenv(f"{prefix}_X2", "0.90")),
            y2=float(os.getenv(f"{prefix}_Y2", "0.55")),
            direction=os.getenv(f"{prefix}_DIRECTION", "both").lower(),
            band_px=int(os.getenv(f"{prefix}_BAND_PX", "36")),
            min_area_px=int(os.getenv(f"{prefix}_MIN_AREA_PX", "1800")),
            cooldown_sec=float(os.getenv(f"{prefix}_COOLDOWN_SEC", "1.5")),
        )


class VirtualLineTrigger:
    def __init__(self, config: Optional[LineTriggerConfig] = None):
        self.config = config or LineTriggerConfig.from_env()
        self.prev_gray: Optional[np.ndarray] = None
        self.prev_dist: Optional[float] = None
        self.prev_centroid: Optional[tuple[float, float]] = None
        self.last_trigger_ts: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _line_points(self, frame_shape: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
        h, w = frame_shape[:2]
        p1 = np.array([self.config.x1 * w, self.config.y1 * h], dtype=np.float32)
        p2 = np.array([self.config.x2 * w, self.config.y2 * h], dtype=np.float32)
        return p1, p2

    @staticmethod
    def _signed_distance(point: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> float:
        v = p2 - p1
        if float(np.linalg.norm(v)) < 1e-6:
            return 0.0
        # 2D cross-product sign: distance scaled by |v|
        return float(np.cross(v, point - p1) / np.linalg.norm(v))

    def _largest_motion_centroid(self, frame: np.ndarray) -> Optional[tuple[float, float]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self.prev_gray is None:
            self.prev_gray = gray
            return None

        diff = cv2.absdiff(self.prev_gray, gray)
        self.prev_gray = gray

        _, motion = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion = cv2.morphologyEx(motion, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        motion = cv2.dilate(motion, np.ones((5, 5), np.uint8), iterations=1)

        contours, _ = cv2.findContours(motion, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(largest))
        if area < self.config.min_area_px:
            return None

        m = cv2.moments(largest)
        if abs(m["m00"]) < 1e-6:
            return None

        cx = float(m["m10"] / m["m00"])
        cy = float(m["m01"] / m["m00"])
        return cx, cy

    def _direction_ok(self, prev_xy: tuple[float, float], curr_xy: tuple[float, float]) -> bool:
        px, py = prev_xy
        cx, cy = curr_xy
        dx = cx - px
        dy = cy - py
        direction = self.config.direction

        if direction == "both":
            return True
        if direction == "up":
            return dy < -1.0
        if direction == "down":
            return dy > 1.0
        if direction == "left":
            return dx < -1.0
        if direction == "right":
            return dx > 1.0
        return True

    def check(self, frame: np.ndarray, timestamp_sec: float) -> bool:
        """Return True when centroid crosses configured line."""
        if not self.enabled:
            return True

        centroid = self._largest_motion_centroid(frame)
        if centroid is None:
            return False

        p1, p2 = self._line_points(frame.shape)
        point = np.array([centroid[0], centroid[1]], dtype=np.float32)
        curr_dist = self._signed_distance(point, p1, p2)

        crossed = False
        if self.prev_dist is not None and self.prev_centroid is not None:
            sign_changed = self.prev_dist * curr_dist < 0
            near_line = min(abs(self.prev_dist), abs(curr_dist)) <= float(self.config.band_px)
            direction_ok = self._direction_ok(self.prev_centroid, centroid)
            cooldown_ok = (timestamp_sec - self.last_trigger_ts) >= self.config.cooldown_sec
            crossed = sign_changed and near_line and direction_ok and cooldown_ok

        self.prev_dist = curr_dist
        self.prev_centroid = centroid

        if crossed:
            self.last_trigger_ts = timestamp_sec
            return True
        return False