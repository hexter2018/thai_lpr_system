"""
crop_validator.py — Detection Crop Validation
===============================================

กรอง YOLO detection ที่ไม่ใช่ป้ายทะเบียนจริงออก ก่อนส่ง OCR

ปัญหา:
- YOLO detect ได้ bbox ที่เป็นข้างรถ / ล้อ / กันชน (false positive)
- ถ่ายตอนรถยังไม่เข้า frame เต็ม → เห็นแค่ครึ่งคัน
- ป้ายทะเบียนเล็กเกินไป (ไกลมาก) → OCR ไม่ได้ผล
- ป้ายเอียงมากเกินไป → OCR อ่านผิด

Solution:
- ตรวจ aspect ratio ของ crop (ป้ายต้องแนวนอน)
- ตรวจขนาดขั้นต่ำ (กว้าง/สูงพิกเซล)
- ตรวจ contrast ในพื้นที่ crop (ป้ายต้องมีตัวอักษร = contrast สูง)
- ตรวจ edge density (ป้ายมีขอบตัวอักษรเยอะ)

ENV:
  CROP_VALIDATOR_ENABLED=true
  CROP_MIN_WIDTH=40              ความกว้างขั้นต่ำ (pixels)
  CROP_MIN_HEIGHT=15             ความสูงขั้นต่ำ (pixels)
  CROP_MIN_ASPECT_RATIO=1.5      width/height ขั้นต่ำ (ป้ายต้องกว้างกว่าสูง)
  CROP_MAX_ASPECT_RATIO=7.0      width/height สูงสุด
  CROP_MIN_CONTRAST=20.0         std deviation ขั้นต่ำ (ต้องมีลาย)
  CROP_MIN_EDGE_DENSITY=0.03     edge pixels / total pixels ขั้นต่ำ
  CROP_SIDE_VIEW_MAX_RATIO=1.2   ถ้า aspect ratio < นี้ อาจเป็นข้างรถ
"""

import logging
import os
from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class CropValidationResult:
    """ผลการตรวจสอบ crop"""
    passed: bool
    reject_reason: str  # "" if passed
    aspect_ratio: float
    width: int
    height: int
    contrast: float
    edge_density: float
    is_side_view: bool


class CropValidator:
    """
    ตรวจสอบ detection crop ว่าเป็นป้ายทะเบียนจริงหรือไม่

    Usage:
        validator = CropValidator()
        result = validator.validate(crop_image)
        if not result.passed:
            log.info("Rejected crop: %s", result.reject_reason)
            # skip OCR
        else:
            # proceed with OCR
    """

    def __init__(self):
        self.enabled = os.getenv("CROP_VALIDATOR_ENABLED", "true").lower() == "true"
        self.min_width = int(os.getenv("CROP_MIN_WIDTH", "40"))
        self.min_height = int(os.getenv("CROP_MIN_HEIGHT", "15"))
        self.min_aspect = float(os.getenv("CROP_MIN_ASPECT_RATIO", "1.5"))
        self.max_aspect = float(os.getenv("CROP_MAX_ASPECT_RATIO", "7.0"))
        self.min_contrast = float(os.getenv("CROP_MIN_CONTRAST", "20.0"))
        self.min_edge_density = float(os.getenv("CROP_MIN_EDGE_DENSITY", "0.03"))
        self.side_view_max_ratio = float(os.getenv("CROP_SIDE_VIEW_MAX_RATIO", "1.2"))

        log.info(
            "CropValidator: enabled=%s min_size=%dx%d aspect=%.1f-%.1f "
            "min_contrast=%.0f min_edge=%.3f",
            self.enabled, self.min_width, self.min_height,
            self.min_aspect, self.max_aspect,
            self.min_contrast, self.min_edge_density,
        )

    def validate(self, crop: np.ndarray) -> CropValidationResult:
        """
        ตรวจสอบว่า crop เป็นป้ายทะเบียนจริงหรือไม่

        Args:
            crop: BGR image (H, W, C) ที่ YOLO crop มา

        Returns:
            CropValidationResult
        """
        if not self.enabled:
            h, w = crop.shape[:2] if crop is not None else (0, 0)
            return CropValidationResult(
                passed=True, reject_reason="",
                aspect_ratio=w / max(h, 1), width=w, height=h,
                contrast=0.0, edge_density=0.0, is_side_view=False,
            )

        if crop is None or crop.size == 0:
            return CropValidationResult(
                passed=False, reject_reason="empty_crop",
                aspect_ratio=0.0, width=0, height=0,
                contrast=0.0, edge_density=0.0, is_side_view=False,
            )

        h, w = crop.shape[:2]
        aspect_ratio = w / max(h, 1)

        # Convert to grayscale for analysis
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop.copy()

        # Calculate metrics
        contrast = float(np.std(gray))
        edge_density = self._edge_density(gray)
        is_side_view = aspect_ratio < self.side_view_max_ratio

        reject_reason = ""

        # === Check 1: Minimum size ===
        if w < self.min_width or h < self.min_height:
            reject_reason = f"too_small ({w}x{h} < {self.min_width}x{self.min_height})"

        # === Check 2: Aspect ratio — ป้ายต้องแนวนอน ===
        elif aspect_ratio < self.min_aspect:
            reject_reason = f"aspect_too_narrow ({aspect_ratio:.2f} < {self.min_aspect})"
            # ป้ายที่ aspect ratio < 1.5 มักเป็นข้างรถ / ล้อ / กันชน
        elif aspect_ratio > self.max_aspect:
            reject_reason = f"aspect_too_wide ({aspect_ratio:.2f} > {self.max_aspect})"
            # อาจเป็น detection ที่ยาวผิดปกติ (เส้นขอบถนน etc.)

        # === Check 3: Contrast — ป้ายต้องมีตัวอักษร ===
        elif contrast < self.min_contrast:
            reject_reason = f"low_contrast ({contrast:.1f} < {self.min_contrast})"
            # พื้นที่สีเดียว (เช่น ตัวถังรถ, พื้นถนน) = contrast ต่ำ

        # === Check 4: Edge density — ป้ายมีขอบตัวอักษรเยอะ ===
        elif edge_density < self.min_edge_density:
            reject_reason = f"low_edge_density ({edge_density:.4f} < {self.min_edge_density})"
            # ถ้าไม่มีขอบตัวอักษร = ไม่น่าจะเป็นป้าย

        passed = reject_reason == ""

        if not passed:
            log.debug(
                "CropValidator REJECT: %s (size=%dx%d aspect=%.2f contrast=%.1f edge=%.4f)",
                reject_reason, w, h, aspect_ratio, contrast, edge_density,
            )

        return CropValidationResult(
            passed=passed,
            reject_reason=reject_reason,
            aspect_ratio=aspect_ratio,
            width=w,
            height=h,
            contrast=contrast,
            edge_density=edge_density,
            is_side_view=is_side_view,
        )

    def _edge_density(self, gray: np.ndarray) -> float:
        """
        คำนวณ edge density — สัดส่วนของ pixel ที่เป็นขอบ

        ป้ายทะเบียนมี edge density สูง (ตัวอักษร + กรอบ)
        ข้างรถ / พื้นถนน มี edge density ต่ำ
        """
        if gray.size == 0:
            return 0.0

        # Canny edge detection
        edges = cv2.Canny(gray, 50, 150)

        # Calculate density = edge pixels / total pixels
        total_pixels = gray.shape[0] * gray.shape[1]
        edge_pixels = np.count_nonzero(edges)

        return edge_pixels / max(total_pixels, 1)

    def validate_bbox(
        self,
        bbox: Tuple[int, int, int, int],
        frame_shape: Tuple[int, int],
    ) -> CropValidationResult:
        """
        ตรวจสอบ bbox โดยไม่ต้องมี crop image (เร็วกว่า)
        ใช้สำหรับ pre-filter ก่อน crop

        Args:
            bbox: (x1, y1, x2, y2) in pixels
            frame_shape: (frame_height, frame_width)
        """
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        aspect_ratio = w / max(h, 1)
        frame_h, frame_w = frame_shape

        reject_reason = ""

        if w < self.min_width or h < self.min_height:
            reject_reason = f"bbox_too_small ({w}x{h})"
        elif aspect_ratio < self.min_aspect:
            reject_reason = f"bbox_aspect_narrow ({aspect_ratio:.2f})"
        elif aspect_ratio > self.max_aspect:
            reject_reason = f"bbox_aspect_wide ({aspect_ratio:.2f})"

        # Check if bbox is at extreme edges (likely partial view / side view)
        margin_x = frame_w * 0.03  # 3% margin
        if x1 < margin_x or x2 > (frame_w - margin_x):
            # bbox อยู่ขอบซ้าย/ขวาของ frame → อาจเป็นข้างรถที่เข้ามาครึ่งเดียว
            if not reject_reason:
                reject_reason = f"bbox_at_edge (x1={x1}, x2={x2}, frame_w={frame_w})"

        # Check if bbox is too far (very small relative to frame)
        bbox_area = w * h
        frame_area = frame_w * frame_h
        area_ratio = bbox_area / max(frame_area, 1)
        if area_ratio < 0.001:  # < 0.1% of frame
            if not reject_reason:
                reject_reason = f"bbox_too_far (area_ratio={area_ratio:.5f})"

        return CropValidationResult(
            passed=reject_reason == "",
            reject_reason=reject_reason,
            aspect_ratio=aspect_ratio,
            width=w,
            height=h,
            contrast=0.0,  # not calculated for bbox-only check
            edge_density=0.0,
            is_side_view=aspect_ratio < self.side_view_max_ratio,
        )