"""
deglare.py — Headlight Deglare Preprocessing for ALPR
======================================================

ปัญหา: ไฟหน้ารถตอนกลางคืนทำให้เกิด glare/flare ที่บังป้าย
       YOLO detect ไม่เจอเพราะ plate region ถูก wash out

วิธีแก้: Preprocessing ก่อนส่ง YOLO
1. Detect saturated regions (headlights)
2. Apply local tone mapping เฉพาะ plate region
3. Enhance contrast ใน plate zone

ทำงานบน GPU worker (process_capture task)
ใช้ OpenCV + numpy (ไม่ต้อง deep learning เพิ่ม)

ENV:
  DEGLARE_ENABLED=true
  DEGLARE_SATURATION_THRESHOLD=240
  DEGLARE_CLAHE_CLIP=3.0
  DEGLARE_CLAHE_GRID=8
"""
import logging
import os
from typing import Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


class HeadlightDeglare:
    """
    Preprocessor ที่ลด headlight glare เพื่อช่วยให้ YOLO detect ป้ายได้
    
    Usage:
        deglare = HeadlightDeglare()
        processed = deglare.process(frame)
        # ส่ง processed ไป YOLO detect
    """
    
    def __init__(self):
        self.enabled = os.getenv("DEGLARE_ENABLED", "true").lower() == "true"
        self.sat_threshold = int(os.getenv("DEGLARE_SATURATION_THRESHOLD", "240"))
        self.clahe_clip = float(os.getenv("DEGLARE_CLAHE_CLIP", "3.0"))
        self.clahe_grid = int(os.getenv("DEGLARE_CLAHE_GRID", "8"))
        
        # Create CLAHE (Contrast Limited Adaptive Histogram Equalization)
        self._clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip,
            tileGridSize=(self.clahe_grid, self.clahe_grid),
        )
        
        log.info(
            "HeadlightDeglare: enabled=%s threshold=%d clahe_clip=%.1f",
            self.enabled, self.sat_threshold, self.clahe_clip,
        )
    
    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        ลด headlight glare ใน frame
        
        Args:
            frame: BGR image (H, W, 3)
            
        Returns:
            Processed BGR image (same size)
        """
        if not self.enabled:
            return frame
        
        h, w = frame.shape[:2]
        
        # Step 1: Detect glare level
        glare_pct = self._detect_glare(frame)
        if glare_pct < 0.1:
            # No significant glare → skip processing
            return frame
        
        log.debug("Deglare: %.1f%% saturated pixels detected", glare_pct)
        
        # Step 2: Convert to LAB for better processing
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        
        # Step 3: Apply CLAHE to L channel (lightness)
        l_enhanced = self._clahe.apply(l_channel)
        
        # Step 4: Tone-map the overexposed areas
        # Create mask of overexposed regions
        overexposed_mask = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) > self.sat_threshold
        
        if overexposed_mask.any():
            # Dilate the mask to cover surrounding bloom/flare
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
            glare_region = cv2.dilate(overexposed_mask.astype(np.uint8), kernel, iterations=2)
            
            # In glare regions, reduce L channel more aggressively
            l_corrected = l_enhanced.copy()
            l_corrected[glare_region > 0] = np.clip(
                l_corrected[glare_region > 0].astype(np.float32) * 0.6, 
                0, 255
            ).astype(np.uint8)
            
            l_enhanced = l_corrected
        
        # Step 5: Focus enhancement on plate region (bottom-center)
        plate_y1 = int(h * 0.65)
        plate_y2 = int(h * 0.98)
        plate_x1 = int(w * 0.20)
        plate_x2 = int(w * 0.80)
        
        # Extra CLAHE pass on plate region only (more aggressive)
        clahe_plate = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
        plate_l = l_enhanced[plate_y1:plate_y2, plate_x1:plate_x2]
        plate_l_enhanced = clahe_plate.apply(plate_l)
        l_enhanced[plate_y1:plate_y2, plate_x1:plate_x2] = plate_l_enhanced
        
        # Step 6: Merge back
        enhanced_lab = cv2.merge([l_enhanced, a_channel, b_channel])
        result = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
        
        # Step 7: Sharpen plate region slightly
        plate_region = result[plate_y1:plate_y2, plate_x1:plate_x2]
        sharp_kernel = np.array([
            [0, -0.5, 0],
            [-0.5, 3, -0.5],
            [0, -0.5, 0],
        ])
        plate_sharpened = cv2.filter2D(plate_region, -1, sharp_kernel)
        result[plate_y1:plate_y2, plate_x1:plate_x2] = np.clip(plate_sharpened, 0, 255)
        
        return result
    
    def _detect_glare(self, frame: np.ndarray) -> float:
        """ตรวจ % ของ pixel ที่ saturated"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        saturated = (gray > self.sat_threshold).mean() * 100
        return saturated
    
    def process_for_detection(
        self, frame: np.ndarray
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        ส่งคืนทั้ง processed frame และ original
        เพื่อให้ YOLO ลอง detect ทั้ง 2 แบบ
        
        Returns:
            (processed_frame, original_frame_if_different)
        """
        processed = self.process(frame)
        
        # Check if processing actually changed anything
        if np.array_equal(processed, frame):
            return frame, None
        
        return processed, frame


# Self-test
if __name__ == "__main__":
    import sys
    import glob
    
    logging.basicConfig(level=logging.DEBUG)
    deglare = HeadlightDeglare()
    
    images = sorted(glob.glob("*.jpg"))
    if not images:
        print("Place test images in current directory")
        sys.exit(0)
    
    for f in images:
        frame = cv2.imread(f)
        if frame is None:
            continue
        
        processed = deglare.process(frame)
        
        out_name = f"deglared_{f}"
        cv2.imwrite(out_name, processed)
        
        # Compare
        orig_plate = frame[int(frame.shape[0]*0.7):, int(frame.shape[1]*0.25):int(frame.shape[1]*0.75)]
        proc_plate = processed[int(processed.shape[0]*0.7):, int(processed.shape[1]*0.25):int(processed.shape[1]*0.75)]
        
        print(f"{f}: plate_contrast {orig_plate.std():.0f} → {proc_plate.std():.0f}  saved: {out_name}")
