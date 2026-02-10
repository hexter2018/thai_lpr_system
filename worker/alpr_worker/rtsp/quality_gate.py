"""
quality_gate.py — Smart Quality Gate สำหรับ ALPR
=================================================

จุดประสงค์: กรองเฟรมที่ไม่มีทางอ่านป้ายได้ออกก่อนจะ save/enqueue
ทำงานบน RTSP producer (ไม่ต้อง GPU)

Filters:
1. PlateRegionChecker  — เช็คว่าบริเวณป้าย (bottom-center) มี contrast เพียงพอ
2. HeadlightGlareDetector — ตรวจ headlight flare ที่จ้าจนบังป้าย
3. IRModeDetector — ตรวจ IR/B&W mode ที่กล้องสลับตอนกลางคืน
4. VehiclePositionEstimator — ประมาณว่ารถอยู่ในตำแหน่งที่เหมาะสมหรือไม่

ใช้ numpy เท่านั้น (ไม่ต้อง opencv/torch)

ENV:
  QUALITY_GATE_ENABLED=true
  QUALITY_GATE_MIN_PLATE_CONTRAST=25.0  # min std ของ plate region
  QUALITY_GATE_MAX_GLARE_PCT=2.0        # max % ของ saturated pixels
  QUALITY_GATE_MIN_COLOR_SATURATION=5.0 # min saturation เพื่อ reject IR mode
"""
import logging
import os
from dataclasses import dataclass
from typing import Tuple, Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class QualityGateResult:
    """ผลการตรวจสอบ quality gate"""
    passed: bool
    score: float          # 0-100 overall quality
    reject_reason: str    # "" if passed
    plate_contrast: float
    glare_pct: float
    is_ir_mode: bool
    vehicle_position: str  # "good", "too_far", "too_close", "side_view", "rear_view"


class QualityGate:
    """
    Smart quality gate สำหรับ ALPR frames
    
    Usage:
        gate = QualityGate()
        result = gate.check(frame_array)
        if result.passed:
            # save and enqueue
        else:
            # skip frame
            log.debug("Rejected: %s", result.reject_reason)
    """
    
    def __init__(self):
        self.enabled = os.getenv("QUALITY_GATE_ENABLED", "true").lower() == "true"
        self.min_plate_contrast = float(os.getenv("QUALITY_GATE_MIN_PLATE_CONTRAST", "25.0"))
        self.max_glare_pct = float(os.getenv("QUALITY_GATE_MAX_GLARE_PCT", "2.0"))
        self.min_color_sat = float(os.getenv("QUALITY_GATE_MIN_COLOR_SATURATION", "5.0"))
        
        # ROI for plate region (normalized 0-1)
        # For toll booth camera: plate appears in bottom-center
        self.plate_roi = {
            "x1": 0.25, "y1": 0.70,
            "x2": 0.75, "y2": 0.95,
        }
        
        log.info(
            "QualityGate: enabled=%s min_contrast=%.0f max_glare=%.1f%%",
            self.enabled, self.min_plate_contrast, self.max_glare_pct,
        )
    
    def check(self, frame: np.ndarray) -> QualityGateResult:
        """
        ตรวจสอบเฟรมว่าคุณภาพเพียงพอสำหรับ ALPR หรือไม่
        
        Args:
            frame: numpy array (H, W, 3) BGR or RGB
            
        Returns:
            QualityGateResult
        """
        if not self.enabled:
            return QualityGateResult(
                passed=True, score=50.0, reject_reason="",
                plate_contrast=0, glare_pct=0, is_ir_mode=False,
                vehicle_position="unknown",
            )
        
        h, w = frame.shape[:2]
        
        # 1. Check plate region contrast
        plate_contrast = self._check_plate_contrast(frame, h, w)
        
        # 2. Check headlight glare
        glare_pct = self._check_glare(frame)
        
        # 3. Check IR/B&W mode
        is_ir = self._check_ir_mode(frame)
        
        # 4. Estimate vehicle position
        vehicle_pos = self._estimate_vehicle_position(frame, h, w)
        
        # === Scoring ===
        score = 50.0  # baseline
        reject_reason = ""
        
        # Plate contrast scoring (most important)
        if plate_contrast < self.min_plate_contrast:
            score -= 30
            reject_reason = f"plate_contrast_low ({plate_contrast:.0f} < {self.min_plate_contrast:.0f})"
        else:
            score += min(20, (plate_contrast - self.min_plate_contrast) * 0.5)
        
        # Glare penalty
        if glare_pct > self.max_glare_pct:
            score -= 20
            if not reject_reason:
                reject_reason = f"headlight_glare ({glare_pct:.1f}% > {self.max_glare_pct:.1f}%)"
        
        # IR mode penalty (plates harder to read in IR)
        if is_ir:
            score -= 10
            if not reject_reason and plate_contrast < self.min_plate_contrast * 1.5:
                reject_reason = f"ir_mode_low_contrast (contrast={plate_contrast:.0f})"
        
        # Vehicle position
        if vehicle_pos in ("too_far", "rear_view"):
            score -= 15
            if not reject_reason:
                reject_reason = f"bad_vehicle_position ({vehicle_pos})"
        elif vehicle_pos == "good":
            score += 10
        
        score = max(0, min(100, score))
        passed = reject_reason == ""
        
        return QualityGateResult(
            passed=passed,
            score=score,
            reject_reason=reject_reason,
            plate_contrast=plate_contrast,
            glare_pct=glare_pct,
            is_ir_mode=is_ir,
            vehicle_position=vehicle_pos,
        )
    
    def _check_plate_contrast(self, frame: np.ndarray, h: int, w: int) -> float:
        """วัด contrast ในบริเวณที่ป้ายควรอยู่"""
        roi = self.plate_roi
        y1 = int(h * roi["y1"])
        y2 = int(h * roi["y2"])
        x1 = int(w * roi["x1"])
        x2 = int(w * roi["x2"])
        
        plate_region = frame[y1:y2, x1:x2]
        if plate_region.size == 0:
            return 0.0
        
        return float(np.std(plate_region))
    
    def _check_glare(self, frame: np.ndarray) -> float:
        """ตรวจ % ของ pixel ที่ saturated (headlight glare)"""
        if len(frame.shape) == 3:
            # Check all channels > 250
            saturated = np.all(frame > 250, axis=2)
        else:
            saturated = frame > 250
        
        return float(saturated.mean() * 100)
    
    def _check_ir_mode(self, frame: np.ndarray) -> bool:
        """ตรวจว่ากล้องอยู่ใน IR mode (ขาวดำ) หรือไม่"""
        if len(frame.shape) < 3 or frame.shape[2] < 3:
            return True  # grayscale = IR
        
        # In IR mode, R ≈ G ≈ B for most pixels
        # Calculate color saturation
        r, g, b = frame[:,:,0].astype(float), frame[:,:,1].astype(float), frame[:,:,2].astype(float)
        max_rgb = np.maximum(np.maximum(r, g), b)
        min_rgb = np.minimum(np.minimum(r, g), b)
        
        # Avoid division by zero
        mask = max_rgb > 10
        if mask.sum() == 0:
            return True
        
        saturation = np.zeros_like(max_rgb)
        saturation[mask] = (max_rgb[mask] - min_rgb[mask]) / max_rgb[mask] * 100
        
        avg_saturation = saturation[mask].mean()
        return avg_saturation < self.min_color_sat
    
    def _estimate_vehicle_position(self, frame: np.ndarray, h: int, w: int) -> str:
        """
        ประมาณตำแหน่งรถจาก brightness distribution
        
        - "good": รถอยู่ center, ขนาดพอเหมาะ
        - "too_far": รถเล็กเกินไป (อยู่ไกล)
        - "too_close": รถใหญ่เกินไป (ใกล้มาก ป้ายอาจไม่อยู่ใน frame)
        - "side_view": เห็นข้างรถ
        - "rear_view": เห็นท้ายรถ (ไฟท้ายแดง)
        """
        # Simple heuristic: check brightness in different quadrants
        center = frame[h//4:3*h//4, w//4:3*w//4]
        bottom = frame[3*h//4:, :]
        
        center_brightness = center.mean()
        bottom_brightness = bottom.mean()
        
        # Check for taillights (red dominant in bottom region)
        if len(frame.shape) == 3 and frame.shape[2] >= 3:
            bottom_r = frame[3*h//4:, :, 0].mean() if frame.shape[2] == 3 else 0
            bottom_g = frame[3*h//4:, :, 1].mean() if frame.shape[2] == 3 else 0
            
            # Red channel significantly higher = taillights = rear view
            if bottom_r > bottom_g * 1.3 and bottom_r > 80:
                return "rear_view"
        
        # Check if vehicle fills most of the frame (too close = side view)
        frame_brightness = frame.mean()
        if frame_brightness < 40:
            # Very dark = vehicle body fills frame = too close
            dark_pct = (frame < 50).mean()
            if dark_pct > 0.6:
                return "too_close"
        
        # Check if vehicle is small (too far)
        # In "too far" frames, most of the frame is road/background
        mid_section = frame[h//3:2*h//3, w//4:3*w//4]
        road_brightness = frame[2*h//3:, w//4:3*w//4].mean()
        
        if center_brightness < 50 and road_brightness > 60:
            return "too_far"
        
        return "good"


# ============================================================
# Self-test with actual production images
# ============================================================
if __name__ == "__main__":
    import glob
    
    logging.basicConfig(level=logging.INFO)
    gate = QualityGate()
    
    # Test with any images in current directory
    images = sorted(glob.glob("*.jpg"))
    if not images:
        print("No .jpg files found. Place test images in current directory.")
        sys.exit(0)
    
    print(f"Testing {len(images)} images:")
    print(f"{'File':50} {'Pass':>5} {'Score':>6} {'Contrast':>9} {'Glare':>6} {'IR':>3} {'Pos':>10} {'Reason'}")
    print("-" * 130)
    
    passed_count = 0
    for f in images:
        from PIL import Image
        img = Image.open(f)
        arr = np.array(img)
        
        result = gate.check(arr)
        passed_count += result.passed
        
        print(
            f"{f:50} {'✅' if result.passed else '❌':>5} "
            f"{result.score:>6.1f} "
            f"{result.plate_contrast:>9.1f} "
            f"{result.glare_pct:>5.1f}% "
            f"{'IR' if result.is_ir_mode else '  ':>3} "
            f"{result.vehicle_position:>10} "
            f"{result.reject_reason}"
        )
    
    print(f"\nPassed: {passed_count}/{len(images)} ({passed_count/len(images)*100:.0f}%)")
