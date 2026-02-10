"""
ROI Zone — กำหนดพื้นที่ที่สนใจสำหรับ RTSP capture

ใช้สัดส่วน (0.0-1.0) เพื่อรองรับทุก resolution
ตัดส่วนที่ไม่จำเป็น (ฟ้า, พื้นถนนไกล, ขอบภาพ) ออกก่อน detect

Usage:
    from alpr_worker.rtsp.roi_zone import ROIZone, ROIConfig

    roi = ROIZone(ROIConfig(x1=0.05, y1=0.15, x2=0.95, y2=0.90))
    cropped, offset = roi.crop(frame)
    # ... detect on cropped ...
    original_bbox = roi.map_bbox_to_original(bbox, offset)
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class ROIConfig:
    """ROI proportional coordinates (0.0 - 1.0)"""
    x1: float = 0.0    # left edge proportion
    y1: float = 0.15   # top edge proportion (ตัดฟ้าออก)
    x2: float = 1.0    # right edge proportion
    y2: float = 0.90   # bottom edge proportion (ตัดพื้นถนนไกลออก)

    def __post_init__(self):
        self.x1 = max(0.0, min(self.x1, 1.0))
        self.y1 = max(0.0, min(self.y1, 1.0))
        self.x2 = max(self.x1 + 0.1, min(self.x2, 1.0))
        self.y2 = max(self.y1 + 0.1, min(self.y2, 1.0))

    @classmethod
    def from_env(cls, prefix: str = "RTSP_ROI") -> "ROIConfig":
        """Load ROI config from environment variables"""
        return cls(
            x1=float(os.getenv(f"{prefix}_X1", "0.0")),
            y1=float(os.getenv(f"{prefix}_Y1", "0.15")),
            x2=float(os.getenv(f"{prefix}_X2", "1.0")),
            y2=float(os.getenv(f"{prefix}_Y2", "0.90")),
        )


class ROIZone:
    """
    Crop frame to Region of Interest before detection.

    ข้อดี:
    - ลดพื้นที่ที่ YOLO ต้อง process → เร็วขึ้น
    - ตัด false positive จากพื้นที่ไม่เกี่ยวข้อง (ป้ายโฆษณา, ฟ้า, ต้นไม้)
    - focus detection ที่เลน/ช่องที่ต้องการเท่านั้น

    ข้อควรระวัง:
    - ต้องปรับ ROI ให้เหมาะกับแต่ละกล้อง (ใช้ debug overlay ช่วย)
    - ROI ที่แคบเกินอาจตัดป้ายที่อยู่ขอบภาพ
    """

    def __init__(self, config: Optional[ROIConfig] = None):
        self.config = config or ROIConfig()
        self._enabled = not (
            self.config.x1 <= 0.01
            and self.config.y1 <= 0.01
            and self.config.x2 >= 0.99
            and self.config.y2 >= 0.99
        )
        if self._enabled:
            log.info(
                "ROI Zone enabled: x1=%.2f y1=%.2f x2=%.2f y2=%.2f",
                self.config.x1, self.config.y1, self.config.x2, self.config.y2,
            )
        else:
            log.info("ROI Zone disabled (full frame)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def crop(self, frame: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """
        Crop frame to ROI region.

        Args:
            frame: BGR image (H, W, C)

        Returns:
            (cropped_frame, (offset_x, offset_y, roi_w, roi_h))
            offset is used to map detections back to original frame coordinates
        """
        if not self._enabled:
            h, w = frame.shape[:2]
            return frame, (0, 0, w, h)

        h, w = frame.shape[:2]
        x1 = int(w * self.config.x1)
        y1 = int(h * self.config.y1)
        x2 = int(w * self.config.x2)
        y2 = int(h * self.config.y2)

        # Clamp to valid range
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))

        cropped = frame[y1:y2, x1:x2]
        return cropped, (x1, y1, x2 - x1, y2 - y1)

    def map_bbox_to_original(
        self,
        bbox: Tuple[int, int, int, int],
        offset: Tuple[int, int, int, int],
    ) -> Tuple[int, int, int, int]:
        """
        Map bbox from ROI-cropped coords back to original frame coords.

        Args:
            bbox: (x1, y1, x2, y2) in ROI coords
            offset: (offset_x, offset_y, roi_w, roi_h) from crop()

        Returns:
            (x1, y1, x2, y2) in original frame coords
        """
        bx1, by1, bx2, by2 = bbox
        ox, oy, _, _ = offset
        return (bx1 + ox, by1 + oy, bx2 + ox, by2 + oy)

    def draw_debug(self, frame: np.ndarray, color=(0, 255, 255), thickness=2) -> np.ndarray:
        """
        Draw ROI rectangle on frame for debugging/visualization.

        Args:
            frame: BGR image to draw on (will be copied)
            color: BGR color tuple for rectangle
            thickness: line thickness

        Returns:
            Copy of frame with ROI rectangle drawn
        """
        if not self._enabled:
            return frame

        h, w = frame.shape[:2]
        x1 = int(w * self.config.x1)
        y1 = int(h * self.config.y1)
        x2 = int(w * self.config.x2)
        y2 = int(h * self.config.y2)

        out = frame.copy()
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
        cv2.putText(
            out, "ROI", (x1 + 5, y1 + 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2,
        )

        # แสดงขนาด ROI เป็น %
        roi_pct = ((x2 - x1) * (y2 - y1)) / (w * h) * 100
        cv2.putText(
            out, f"{roi_pct:.0f}% of frame",
            (x1 + 5, y1 + 50),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )

        return out


# === Quick self-test ===
if __name__ == "__main__":
    import sys

    print("ROI Zone Self-Test")
    print("=" * 40)

    # Test 1: Basic crop
    roi = ROIZone(ROIConfig(x1=0.1, y1=0.2, x2=0.9, y2=0.8))
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cropped, offset = roi.crop(frame)
    print(f"Original: {frame.shape}")
    print(f"Cropped:  {cropped.shape}")
    print(f"Offset:   {offset}")
    assert cropped.shape[0] < frame.shape[0], "Height should be smaller"
    assert cropped.shape[1] < frame.shape[1], "Width should be smaller"
    print("✅ Basic crop OK")

    # Test 2: Bbox mapping
    bbox = (100, 50, 200, 100)
    mapped = roi.map_bbox_to_original(bbox, offset)
    print(f"ROI bbox:      {bbox}")
    print(f"Original bbox: {mapped}")
    assert mapped[0] == bbox[0] + offset[0], "X mapping wrong"
    assert mapped[1] == bbox[1] + offset[1], "Y mapping wrong"
    print("✅ Bbox mapping OK")

    # Test 3: Full frame (disabled)
    roi_full = ROIZone(ROIConfig(x1=0.0, y1=0.0, x2=1.0, y2=1.0))
    assert not roi_full.enabled, "Should be disabled for full frame"
    cropped2, offset2 = roi_full.crop(frame)
    assert cropped2.shape == frame.shape, "Should return full frame"
    print("✅ Full frame (disabled) OK")

    # Test 4: From env
    os.environ["RTSP_ROI_X1"] = "0.05"
    os.environ["RTSP_ROI_Y1"] = "0.15"
    os.environ["RTSP_ROI_X2"] = "0.95"
    os.environ["RTSP_ROI_Y2"] = "0.90"
    roi_env = ROIZone(ROIConfig.from_env())
    assert roi_env.enabled
    print("✅ From env OK")

    print()
    print("All tests passed! ✅")