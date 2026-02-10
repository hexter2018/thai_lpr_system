"""
Enhanced Quality Filter Module for RTSP Frame Producer

ปรับปรุงจากเวอร์ชันเดิม เพิ่ม:
- Glare detection (ตรวจจับแสงสะท้อน)
- Contrast analysis (วิเคราะห์ความคมชัด)
- Adaptive thresholding (ปรับ threshold ตามเวลา)
- Night mode support (รองรับกลางคืน)

Author: Enhanced for Thai ALPR System
Date: 2026-02-09
"""

import logging
from collections import deque
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class EnhancedQualityScorer:
    """
    Quality Scorer ที่ปรับปรุงสำหรับกลางคืนและแสงสะท้อน
    
    Metrics:
    1. Sharpness (Laplacian variance) - ความคมชัด
    2. Brightness (mean pixel value) - ความสว่าง
    3. Contrast (Michelson contrast) - ความต่างของสี
    4. Glare penalty (over-exposed areas) - ลดคะแนนเมื่อมีแสงสะท้อน
    
    Score range: 0-100
    """
    
    def __init__(self, min_score: float = 35.0):
        """
        Args:
            min_score: Minimum quality score to accept (0-100)
                      ค่าเริ่มต้นลดจาก 40 → 35 เพื่อรองรับกลางคืน
        """
        self.min_score = min_score
    
    def _detect_glare(self, gray: np.ndarray) -> float:
        """
        ตรวจจับแสงสะท้อน (pixels ที่สว่างเกินไป)
        
        Args:
            gray: Grayscale image
            
        Returns:
            Percentage of glare pixels (0-100)
        """
        # Pixels ที่สว่างมากผิดปกติ (> 240 จาก 255)
        glare_mask = gray > 240
        glare_percentage = (np.count_nonzero(glare_mask) / gray.size) * 100
        return glare_percentage
    
    def _calculate_contrast(self, gray: np.ndarray) -> float:
        """
        คำนวณ Michelson contrast
        
        Formula: (max - min) / (max + min) * 100
        
        Args:
            gray: Grayscale image
            
        Returns:
            Contrast score (0-100)
        """
        min_val = float(gray.min())
        max_val = float(gray.max())
        
        if max_val + min_val == 0:
            return 0.0
        
        contrast = ((max_val - min_val) / (max_val + min_val)) * 100
        return contrast
    
    def _detect_blur(self, gray: np.ndarray) -> float:
        """
        ตรวจจับความเบลอด้วย Laplacian variance
        
        Args:
            gray: Grayscale image
            
        Returns:
            Blur score (0-100), higher = sharper
        """
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = laplacian.var()
        
        # Normalize to 0-100
        # High variance (>100) = sharp, low (<10) = blurry
        blur_score = min(100, (variance / 100) * 100)
        return blur_score
    
    def score(self, frame: np.ndarray) -> float:
        """
        Calculate quality score for frame (Enhanced version)
        
        Args:
            frame: BGR color image
            
        Returns:
            Quality score (0-100)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Sharpness (Laplacian variance)
        sharpness_score = self._detect_blur(gray)
        
        # 2. Brightness (ปรับช่วงให้กว้างขึ้นสำหรับกลางคืน)
        brightness = gray.mean()
        
        # Ideal brightness: 70-190 (กว้างกว่าเดิม)
        if 70 <= brightness <= 190:
            brightness_score = 100.0
        elif brightness < 70:
            # กลางคืนมาก (penalty น้อยลง)
            brightness_score = max(20.0, (brightness / 70) * 100)
        else:
            # สว่างเกินไป
            brightness_score = max(0.0, 100 - ((brightness - 190) / 65) * 100)
        
        # 3. Contrast (ใหม่ - สำคัญสำหรับกลางคืน)
        contrast = self._calculate_contrast(gray)
        # Scale contrast to 0-100 (contrast สูง = ดี)
        contrast_score = min(100.0, contrast * 2.0)
        
        # 4. Glare penalty (ใหม่ - ลดคะแนนเมื่อมีแสงสะท้อน)
        glare_pct = self._detect_glare(gray)
        # Max penalty = 30 points (ถ้ามีแสงสะท้อนมาก)
        glare_penalty = min(30.0, glare_pct * 3.0)
        
        # Combined score with new weights
        # - Sharpness: 40% (สำคัญที่สุด)
        # - Brightness: 25% (ลดลงจากเดิม)
        # - Contrast: 25% (เพิ่มใหม่ - สำคัญสำหรับกลางคืน)
        # - Glare: -penalty (ลดคะแนน)
        score = (
            sharpness_score * 0.40 +
            brightness_score * 0.25 +
            contrast_score * 0.25
        ) - glare_penalty
        
        # Clamp to 0-100
        final_score = max(0.0, min(100.0, score))
        
        return final_score
    
    def is_acceptable(self, frame: np.ndarray) -> bool:
        """
        Check if frame quality is acceptable
        
        Args:
            frame: BGR color image
            
        Returns:
            True if quality >= min_score
        """
        return self.score(frame) >= self.min_score


class AdaptiveMotionDetector:
    """
    Motion Detector ที่ปรับตัวตามเวลา (กลางวัน/กลางคืน)
    
    กลางวัน: ใช้ threshold ต่ำ (sensitive)
    กลางคืน: ใช้ threshold สูง (less sensitive) เพราะ noise มากกว่า
    """
    
    def __init__(
        self, 
        day_threshold: float = 5.0,
        night_threshold: float = 8.0,
        night_brightness_level: float = 80.0
    ):
        """
        Args:
            day_threshold: Motion threshold for daytime (% pixels changed)
            night_threshold: Motion threshold for nighttime (higher = less sensitive)
            night_brightness_level: Brightness threshold to detect night (0-255)
        """
        self.day_threshold = day_threshold
        self.night_threshold = night_threshold
        self.night_brightness_level = night_brightness_level
        self.prev_frame: Optional[np.ndarray] = None
    
    def _is_night(self, gray: np.ndarray) -> bool:
        """
        ตรวจสอบว่าเป็นกลางคืนหรือไม่
        
        Args:
            gray: Grayscale image
            
        Returns:
            True if nighttime
        """
        avg_brightness = gray.mean()
        return avg_brightness < self.night_brightness_level
    
    def has_motion(self, frame: np.ndarray) -> bool:
        """
        Check if frame has motion compared to previous frame
        (Adaptive version - ปรับตามเวลา)
        
        Args:
            frame: BGR color image
            
        Returns:
            True if motion detected
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        # First frame always has "motion"
        if self.prev_frame is None:
            self.prev_frame = gray
            return True
        
        # Adaptive threshold based on time of day
        is_night = self._is_night(gray)
        threshold = self.night_threshold if is_night else self.day_threshold
        
        # Compute absolute difference
        diff = cv2.absdiff(self.prev_frame, gray)
        
        # Threshold (ใช้ค่าสูงขึ้นสำหรับกลางคืนเพื่อลด noise)
        binary_threshold = 30 if is_night else 25
        _, thresh = cv2.threshold(diff, binary_threshold, 255, cv2.THRESH_BINARY)
        
        # Count changed pixels
        total_pixels = thresh.shape[0] * thresh.shape[1]
        changed_pixels = np.count_nonzero(thresh)
        change_percentage = (changed_pixels / total_pixels) * 100
        
        # Update previous frame
        self.prev_frame = gray
        
        # Log for debugging (เฉพาะเมื่อใกล้ threshold)
        if abs(change_percentage - threshold) < 2.0:
            mode = "NIGHT" if is_night else "DAY"
            log.debug(
                f"Motion: {change_percentage:.2f}% (threshold={threshold:.1f}, mode={mode})"
            )
        
        return change_percentage >= threshold


class FrameDeduplicator:
    """
    Detect duplicate frames using perceptual hashing
    (เวอร์ชันเดิม - ใช้ได้ดีอยู่แล้ว)
    
    Algorithm:
    1. Resize to 8x8
    2. Convert to grayscale
    3. Compute average pixel value
    4. Create hash: 1 if pixel > average, 0 otherwise
    5. Compare with recent hashes using Hamming distance
    """
    
    def __init__(
        self,
        cache_size: int = 50,
        threshold: int = 5,
        hash_size: int = 8
    ):
        """
        Args:
            cache_size: Number of recent hashes to keep
            threshold: Maximum Hamming distance to consider duplicate
            hash_size: Size of perceptual hash (8 = 64-bit hash)
        """
        self.cache_size = cache_size
        self.threshold = threshold
        self.hash_size = hash_size
        self.recent_hashes = deque(maxlen=cache_size)
    
    def _compute_hash(self, frame: np.ndarray) -> int:
        """
        Compute perceptual hash for frame
        
        Args:
            frame: BGR color image
            
        Returns:
            64-bit integer hash
        """
        # Resize to hash_size x hash_size
        resized = cv2.resize(frame, (self.hash_size, self.hash_size))
        
        # Convert to grayscale
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        
        # Compute average
        avg = gray.mean()
        
        # Create binary hash
        hash_bits = (gray > avg).flatten()
        
        # Convert to integer
        hash_int = 0
        for i, bit in enumerate(hash_bits):
            if bit:
                hash_int |= (1 << i)
        
        return hash_int
    
    def _hamming_distance(self, hash1: int, hash2: int) -> int:
        """
        Calculate Hamming distance between two hashes
        
        Args:
            hash1, hash2: Integer hashes to compare
            
        Returns:
            Number of differing bits
        """
        xor = hash1 ^ hash2
        distance = 0
        while xor:
            distance += xor & 1
            xor >>= 1
        return distance
    
    def is_duplicate(self, frame: np.ndarray) -> bool:
        """
        Check if frame is duplicate of recent frames
        
        Args:
            frame: BGR color image
            
        Returns:
            True if duplicate, False otherwise
        """
        current_hash = self._compute_hash(frame)
        
        # Check against recent hashes
        for recent_hash in self.recent_hashes:
            distance = self._hamming_distance(current_hash, recent_hash)
            if distance <= self.threshold:
                return True
        
        # Not a duplicate, add to cache
        self.recent_hashes.append(current_hash)
        return False


# ===== Backward Compatibility Aliases =====
# เพื่อให้โค้ดเดิมยังใช้งานได้

class MotionDetector(AdaptiveMotionDetector):
    """Alias for backward compatibility"""
    def __init__(self, threshold: float = 5.0):
        super().__init__(day_threshold=threshold, night_threshold=threshold * 1.6)


class QualityScorer(EnhancedQualityScorer):
    """Alias for backward compatibility"""
    pass


# ===== Convenience Testing Functions =====

def test_enhanced_quality_scorer():
    """Test enhanced quality scorer"""
    scorer = EnhancedQualityScorer(min_score=35.0)
    
    print("Testing Enhanced Quality Scorer...")
    
    # Test 1: Blurry frame (low sharpness)
    blurry = np.ones((480, 640, 3), dtype=np.uint8) * 128
    blurry = cv2.GaussianBlur(blurry, (51, 51), 0)
    score1 = scorer.score(blurry)
    print(f"  Blurry frame: {score1:.1f}")
    
    # Test 2: Sharp frame (high sharpness)
    sharp = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    score2 = scorer.score(sharp)
    print(f"  Sharp frame: {score2:.1f}")
    
    # Test 3: Night frame (low brightness, high contrast)
    night = np.zeros((480, 640, 3), dtype=np.uint8)
    night[100:200, 200:400] = 255  # Bright area (like headlights)
    score3 = scorer.score(night)
    print(f"  Night frame: {score3:.1f}")
    
    # Test 4: Glare frame (over-exposed)
    glare = np.ones((480, 640, 3), dtype=np.uint8) * 250
    score4 = scorer.score(glare)
    print(f"  Glare frame: {score4:.1f}")
    
    assert score2 > score1, "Sharp should score higher than blurry"
    assert score3 < score2, "Night should score lower than normal"
    assert score4 < score2, "Glare should score lower than normal"
    
    print("✓ Enhanced quality scorer tests passed")


def test_adaptive_motion_detector():
    """Test adaptive motion detector"""
    detector = AdaptiveMotionDetector(
        day_threshold=5.0, 
        night_threshold=8.0
    )
    
    print("\nTesting Adaptive Motion Detector...")
    
    # Test 1: Day scene - no motion
    day_frame1 = np.ones((480, 640, 3), dtype=np.uint8) * 150
    day_frame2 = day_frame1.copy()
    
    assert detector.has_motion(day_frame1) == True  # First frame
    assert detector.has_motion(day_frame2) == False  # No change
    print("  Day scene (no motion): PASS")
    
    # Test 2: Day scene - with motion
    day_frame3 = np.ones((480, 640, 3), dtype=np.uint8) * 180
    assert detector.has_motion(day_frame3) == True
    print("  Day scene (with motion): PASS")
    
    # Test 3: Night scene
    night_frame1 = np.ones((480, 640, 3), dtype=np.uint8) * 50
    night_frame2 = np.ones((480, 640, 3), dtype=np.uint8) * 55
    
    detector_night = AdaptiveMotionDetector()
    assert detector_night.has_motion(night_frame1) == True  # First frame
    # Small change in night - should need more change to trigger
    result = detector_night.has_motion(night_frame2)
    print(f"  Night scene (small change): {result}")
    
    print("✓ Adaptive motion detector tests passed")


if __name__ == "__main__":
    """Run tests"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Enhanced Quality Filter Tests")
    print("=" * 60)
    
    test_enhanced_quality_scorer()
    test_adaptive_motion_detector()
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)