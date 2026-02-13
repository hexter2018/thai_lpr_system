"""
zone_trigger.py — Multi-Zone Capture Trigger
=============================================

กำหนดพื้นที่ polygon หลายจุดเพื่อ trigger capture
เหมาะสำหรับ toll booth หลายเลน หรือกล้องที่มีหลาย capture point

ต่างจาก Virtual Line:
  - Virtual Line = trigger เมื่อรถข้ามเส้น (มีทิศทาง)
  - Zone Trigger = trigger เมื่อรถ "อยู่ใน" zone นิ่งๆ (ไม่มีทิศทาง)
  ⭐ เหมาะกับจุดจอดจ่ายเงิน / ด่านที่รถต้องหยุด

Algorithm:
  1. ตรวจ motion ใน zone ด้วย frame diff
  2. คำนวณสัดส่วนพื้นที่ใน zone ที่เปลี่ยน (fill_ratio)
  3. ถ้า fill_ratio >= min_fill_ratio → trigger
  4. มี cooldown เพื่อป้องกัน duplicate

Usage:
    from alpr_worker.rtsp.zone_trigger import ZoneTrigger, CaptureZone, load_zones_from_env

    zones = load_zones_from_env()
    trigger = ZoneTrigger(zones)

    while True:
        ret, frame = cap.read()
        if trigger.check(frame, time.time()):
            # save + enqueue this frame

ENV:
  CAPTURE_ZONE_ENABLED=true
  CAPTURE_ZONE_COUNT=2

  CAPTURE_ZONE_1_NAME=lane_left
  CAPTURE_ZONE_1_POINTS=0.10,0.50;0.30,0.50;0.30,0.85;0.10,0.85
  CAPTURE_ZONE_1_MIN_FILL=0.12
  CAPTURE_ZONE_1_COOLDOWN=2.0

  CAPTURE_ZONE_2_NAME=lane_right
  CAPTURE_ZONE_2_POINTS=0.55,0.50;0.85,0.50;0.85,0.85;0.55,0.85
  CAPTURE_ZONE_2_MIN_FILL=0.12
  CAPTURE_ZONE_2_COOLDOWN=2.0
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ─── Data Classes ────────────────────────────────────────────


@dataclass
class CaptureZone:
    """
    Polygon zone สำหรับ trigger capture

    points: list ของ (x, y) normalized 0.0-1.0
            เช่น [(0.1,0.5), (0.3,0.5), (0.3,0.85), (0.1,0.85)]
            ต้องมีอย่างน้อย 3 จุด (triangle ขึ้นไป)
    """
    name: str
    points: List[Tuple[float, float]]  # normalized 0.0–1.0
    min_fill_ratio: float = 0.12       # สัดส่วนพื้นที่ที่ต้องเปลี่ยนขั้นต่ำ (0–1)
    cooldown_sec: float = 2.0          # วินาที cooldown หลัง trigger

    def __post_init__(self):
        if len(self.points) < 3:
            raise ValueError(f"Zone '{self.name}' needs at least 3 points, got {len(self.points)}")
        self.min_fill_ratio = max(0.01, min(self.min_fill_ratio, 1.0))
        self.cooldown_sec = max(0.0, self.cooldown_sec)

    def pixel_points(self, frame_w: int, frame_h: int) -> np.ndarray:
        """แปลง normalized → pixel coordinates"""
        pts = [(int(x * frame_w), int(y * frame_h)) for x, y in self.points]
        return np.array(pts, dtype=np.int32)

    @classmethod
    def from_env_string(cls, name: str, points_str: str,
                        min_fill: float = 0.12,
                        cooldown: float = 2.0) -> "CaptureZone":
        """
        Parse points จาก ENV string: "0.1,0.5;0.3,0.5;0.3,0.85;0.1,0.85"
        """
        points: List[Tuple[float, float]] = []
        for pair in points_str.strip().split(";"):
            pair = pair.strip()
            if not pair:
                continue
            parts = pair.split(",")
            if len(parts) != 2:
                raise ValueError(f"Invalid point format '{pair}' in zone '{name}'")
            x, y = float(parts[0].strip()), float(parts[1].strip())
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError(f"Point ({x},{y}) out of range [0,1] in zone '{name}'")
            points.append((x, y))
        return cls(name=name, points=points, min_fill_ratio=min_fill, cooldown_sec=cooldown)


@dataclass
class ZoneTriggerResult:
    """ผลลัพธ์จากการตรวจสอบ zone"""
    triggered: bool
    triggered_zones: List[str] = field(default_factory=list)  # ชื่อ zone ที่ trigger
    fill_ratios: dict = field(default_factory=dict)            # {zone_name: fill_ratio}


# ─── Main Class ──────────────────────────────────────────────


class ZoneTrigger:
    """
    ตรวจจับการเคลื่อนไหวใน polygon zones หลายจุด

    Usage:
        zones = load_zones_from_env()
        trigger = ZoneTrigger(zones)

        while True:
            ret, frame = cap.read()
            result = trigger.check_full(frame, time.time())
            if result.triggered:
                for z in result.triggered_zones:
                    print(f"Zone '{z}' triggered!")
                save_and_enqueue(frame)
    """

    def __init__(self, zones: List[CaptureZone]):
        if not zones:
            raise ValueError("ZoneTrigger requires at least 1 zone")
        self.zones = zones
        self._prev_gray: Optional[np.ndarray] = None
        self._last_trigger: dict = {z.name: 0.0 for z in zones}  # {name: timestamp}
        log.info("ZoneTrigger initialized with %d zones: %s",
                 len(zones), [z.name for z in zones])

    # ── Public API ──────────────────────────────────────────

    def check(self, frame: np.ndarray, timestamp_sec: float) -> bool:
        """
        Simple bool check — True ถ้า zone ใดก็ได้ trigger
        (ใช้แทน VirtualLineTrigger.check() ได้ตรงๆ)
        """
        return self.check_full(frame, timestamp_sec).triggered

    def check_full(self, frame: np.ndarray, timestamp_sec: float) -> ZoneTriggerResult:
        """
        ตรวจสอบทุก zone แล้วคืน ZoneTriggerResult พร้อม detail
        """
        # คำนวณ motion mask จาก frame diff
        motion_mask = self._compute_motion_mask(frame)

        triggered_zones: List[str] = []
        fill_ratios: dict = {}

        for zone in self.zones:
            h, w = frame.shape[:2]
            pts = zone.pixel_points(w, h)

            # สร้าง polygon mask สำหรับ zone นี้
            zone_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(zone_mask, [pts], 255)

            # คำนวณ fill ratio
            zone_area = int(zone_mask.sum() / 255)
            if zone_area == 0:
                fill_ratios[zone.name] = 0.0
                continue

            motion_in_zone = cv2.bitwise_and(motion_mask, zone_mask)
            motion_pixels = int(motion_in_zone.sum() / 255)
            fill_ratio = motion_pixels / zone_area
            fill_ratios[zone.name] = round(fill_ratio, 4)

            # เช็ค cooldown
            cooldown_passed = (timestamp_sec - self._last_trigger[zone.name]) >= zone.cooldown_sec

            if fill_ratio >= zone.min_fill_ratio and cooldown_passed:
                triggered_zones.append(zone.name)
                self._last_trigger[zone.name] = timestamp_sec
                log.info("Zone '%s' triggered: fill=%.1f%% (min=%.1f%%)",
                         zone.name, fill_ratio * 100, zone.min_fill_ratio * 100)

        return ZoneTriggerResult(
            triggered=len(triggered_zones) > 0,
            triggered_zones=triggered_zones,
            fill_ratios=fill_ratios,
        )

    def draw_zones(self, frame: np.ndarray,
                   fill_ratios: Optional[dict] = None,
                   show_labels: bool = True) -> np.ndarray:
        """
        วาด zones บน frame สำหรับ debug/visualization

        Args:
            frame: BGR frame
            fill_ratios: ผลจาก check_full() สำหรับ colorize
            show_labels: แสดงชื่อ zone + fill ratio

        Returns:
            Frame with zones drawn (copy)
        """
        out = frame.copy()
        h, w = out.shape[:2]

        for zone in self.zones:
            pts = zone.pixel_points(w, h)
            fill = (fill_ratios or {}).get(zone.name, 0.0)
            is_active = fill >= zone.min_fill_ratio

            # สี: เขียว = active, ฟ้า = inactive
            color = (0, 255, 80) if is_active else (255, 200, 0)
            alpha_color = (0, 100, 30) if is_active else (100, 80, 0)

            # วาด fill semi-transparent
            overlay = out.copy()
            cv2.fillPoly(overlay, [pts], alpha_color)
            cv2.addWeighted(overlay, 0.25, out, 0.75, 0, out)

            # วาดขอบ
            cv2.polylines(out, [pts], isClosed=True, color=color, thickness=2)

            if show_labels:
                # ตำแหน่ง label = centroid ของ polygon
                cx = int(pts[:, 0].mean())
                cy = int(pts[:, 1].mean())
                label = f"{zone.name}"
                if fill_ratios:
                    label += f" {fill*100:.0f}%"
                cv2.putText(out, label, (cx - 30, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)

        return out

    def reset(self):
        """Reset motion state (เรียกเมื่อ reconnect stream)"""
        self._prev_gray = None
        log.info("ZoneTrigger: motion state reset")

    # ── Internal ────────────────────────────────────────────

    def _compute_motion_mask(self, frame: np.ndarray) -> np.ndarray:
        """
        คำนวณ binary motion mask จาก frame diff
        Returns: uint8 array ขนาดเดียวกับ frame (0 or 255)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)

        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            return np.zeros_like(gray)

        diff = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray

        _, motion = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
        # Morphological open เพื่อลด noise เล็กๆ
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        motion = cv2.morphologyEx(motion, cv2.MORPH_OPEN, kernel)
        return motion


# ─── Factory / ENV Loader ────────────────────────────────────


def load_zones_from_env(prefix: str = "CAPTURE_ZONE") -> List[CaptureZone]:
    """
    โหลด zones จาก ENV variables

    ENV format:
        CAPTURE_ZONE_ENABLED=true
        CAPTURE_ZONE_COUNT=2

        CAPTURE_ZONE_1_NAME=lane_left
        CAPTURE_ZONE_1_POINTS=0.10,0.50;0.30,0.50;0.30,0.85;0.10,0.85
        CAPTURE_ZONE_1_MIN_FILL=0.12
        CAPTURE_ZONE_1_COOLDOWN=2.0

        CAPTURE_ZONE_2_NAME=lane_right
        CAPTURE_ZONE_2_POINTS=0.55,0.50;0.85,0.50;0.85,0.85;0.55,0.85
        CAPTURE_ZONE_2_MIN_FILL=0.12
        CAPTURE_ZONE_2_COOLDOWN=2.0

    Returns:
        List[CaptureZone] — empty list ถ้า disabled หรือไม่มี config
    """
    enabled = os.getenv(f"{prefix}_ENABLED", "false").lower() == "true"
    if not enabled:
        return []

    count = int(os.getenv(f"{prefix}_COUNT", "0"))
    if count == 0:
        return []

    zones: List[CaptureZone] = []
    for i in range(1, count + 1):
        pfx = f"{prefix}_{i}"
        name = os.getenv(f"{pfx}_NAME", f"zone_{i}")
        points_str = os.getenv(f"{pfx}_POINTS", "").strip()
        min_fill = float(os.getenv(f"{pfx}_MIN_FILL", "0.12"))
        cooldown = float(os.getenv(f"{pfx}_COOLDOWN", "2.0"))

        if not points_str:
            log.warning("Zone %d ('%s') has no POINTS — skipped", i, name)
            continue

        try:
            zone = CaptureZone.from_env_string(name, points_str, min_fill, cooldown)
            zones.append(zone)
            log.info("Zone loaded: %s (%d pts, min_fill=%.0f%%, cooldown=%.1fs)",
                     name, len(zone.points), min_fill * 100, cooldown)
        except Exception as e:
            log.error("Failed to load zone %d ('%s'): %s", i, name, e)

    return zones


def create_default_zones_for_toll_booth() -> List[CaptureZone]:
    """
    Zone เริ่มต้นสำหรับ toll booth 2 เลน (ใช้เป็น reference)
    """
    return [
        CaptureZone(
            name="lane_left",
            points=[(0.08, 0.45), (0.42, 0.45), (0.42, 0.88), (0.08, 0.88)],
            min_fill_ratio=0.12,
            cooldown_sec=2.0,
        ),
        CaptureZone(
            name="lane_right",
            points=[(0.53, 0.45), (0.90, 0.45), (0.90, 0.88), (0.53, 0.88)],
            min_fill_ratio=0.12,
            cooldown_sec=2.0,
        ),
    ]


# ─── Self-test ───────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="[%(levelname)s] %(name)s: %(message)s")

    print("ZoneTrigger Self-Test")
    print("=" * 50)

    # ── Test 1: Basic zone check ──
    print("\n[1] Basic zone check")
    zones = [
        CaptureZone("center", [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)],
                    min_fill_ratio=0.05, cooldown_sec=0.1),
    ]
    trigger = ZoneTrigger(zones)

    frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
    frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
    # เพิ่ม motion ตรงกลาง (ใน zone)
    frame2[150:300, 200:400] = 200

    r1 = trigger.check_full(frame1, 0.0)
    r2 = trigger.check_full(frame2, 1.0)

    assert not r1.triggered, "Frame 1 (blank→blank) should NOT trigger"
    assert r2.triggered, f"Frame 2 (has motion in zone) should trigger, fill={r2.fill_ratios}"
    print(f"  ✅ Frame1 triggered={r1.triggered} | Frame2 triggered={r2.triggered}")
    print(f"     Fill ratios: {r2.fill_ratios}")

    # ── Test 2: Cooldown ──
    print("\n[2] Cooldown check")
    trigger2 = ZoneTrigger([
        CaptureZone("zone_a", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
                    min_fill_ratio=0.01, cooldown_sec=5.0),
    ])
    f_a = np.zeros((480, 640, 3), dtype=np.uint8)
    f_b = np.ones((480, 640, 3), dtype=np.uint8) * 200

    trigger2.check_full(f_a, 0.0)
    r_first = trigger2.check_full(f_b, 1.0)    # should trigger
    r_second = trigger2.check_full(f_b, 2.0)   # cooldown → no trigger
    r_third = trigger2.check_full(f_b, 10.0)   # after cooldown → trigger

    assert r_first.triggered, "First should trigger"
    assert not r_second.triggered, "Second should be in cooldown"
    assert r_third.triggered, "Third should trigger (cooldown expired)"
    print(f"  ✅ First={r_first.triggered} Second(cooldown)={r_second.triggered} Third={r_third.triggered}")

    # ── Test 3: ENV loader ──
    print("\n[3] ENV loader")
    os.environ["CAPTURE_ZONE_ENABLED"] = "true"
    os.environ["CAPTURE_ZONE_COUNT"] = "2"
    os.environ["CAPTURE_ZONE_1_NAME"] = "PCN_L4_lane1"
    os.environ["CAPTURE_ZONE_1_POINTS"] = "0.10,0.50;0.40,0.50;0.40,0.85;0.10,0.85"
    os.environ["CAPTURE_ZONE_1_MIN_FILL"] = "0.10"
    os.environ["CAPTURE_ZONE_2_NAME"] = "PCN_L4_lane2"
    os.environ["CAPTURE_ZONE_2_POINTS"] = "0.55,0.50;0.88,0.50;0.88,0.85;0.55,0.85"
    os.environ["CAPTURE_ZONE_2_MIN_FILL"] = "0.10"

    loaded = load_zones_from_env()
    assert len(loaded) == 2
    assert loaded[0].name == "PCN_L4_lane1"
    assert len(loaded[0].points) == 4
    print(f"  ✅ Loaded {len(loaded)} zones from ENV")
    for z in loaded:
        print(f"     {z.name}: {len(z.points)} pts, min_fill={z.min_fill_ratio}")

    # ── Test 4: draw_zones (visual) ──
    print("\n[4] draw_zones")
    sample_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    trigger_env = ZoneTrigger(loaded)
    visualized = trigger_env.draw_zones(sample_frame,
                                        fill_ratios={"PCN_L4_lane1": 0.25, "PCN_L4_lane2": 0.04})
    assert visualized.shape == sample_frame.shape
    assert not np.array_equal(visualized, sample_frame), "Should have drawn something"
    print(f"  ✅ draw_zones returned {visualized.shape} frame")

    # ── Test 5: parse error handling ──
    print("\n[5] Error handling")
    os.environ["CAPTURE_ZONE_ENABLED"] = "false"
    empty = load_zones_from_env()
    assert empty == [], "Should return empty when disabled"
    print("  ✅ Returns empty when CAPTURE_ZONE_ENABLED=false")

    print("\n" + "=" * 50)
    print("✅ All ZoneTrigger tests passed!")