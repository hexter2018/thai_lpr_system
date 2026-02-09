"""
Quality Filter Module for RTSP Frame Producer

Provides:
- Motion Detection (frame differencing)
- Quality Scoring (sharpness + brightness)
- Frame Deduplication (perceptual hashing)
"""

import logging
from collections import deque
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class MotionDetector:
    """
    Detect motion between frames using frame differencing
    
    Algorithm:
    1. Convert to grayscale
    2. Apply Gaussian blur
    3. Compute absolute difference with previous frame
    4. Threshold and count non-zero pixels
    """
    
    def __init__(self, threshold: float = 5.0):
        """
        Args:
            threshold: Percentage of pixels that must change to detect motion (0-100)
        """
        self.threshold = threshold
        self.prev_frame: Optional[np.ndarray] = None
    
    def has_motion(self, frame: np.ndarray) -> bool:
        """
        Check if frame has motion compared to previous frame
        
        Returns:
            True if motion detected, False otherwise
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        # First frame always has "motion"
        if self.prev_frame is None:
            self.prev_frame = gray
            return True
        
        # Compute difference
        diff = cv2.absdiff(self.prev_frame, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        # Count changed pixels
        total_pixels = thresh.shape[0] * thresh.shape[1]
        changed_pixels = np.count_nonzero(thresh)
        change_percentage = (changed_pixels / total_pixels) * 100
        
        # Update previous frame
        self.prev_frame = gray
        
        return change_percentage >= self.threshold


class QualityScorer:
    """
    Score frame quality based on sharpness and brightness
    
    Metrics:
    - Sharpness: Laplacian variance (focus quality)
    - Brightness: Mean pixel value
    
    Score range: 0-100
    """
    
    def __init__(self, min_score: float = 40.0):
        """
        Args:
            min_score: Minimum quality score to accept (0-100)
        """
        self.min_score = min_score
    
    def score(self, frame: np.ndarray) -> float:
        """
        Calculate quality score for frame
        
        Returns:
            Quality score (0-100)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Sharpness (Laplacian variance)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness_variance = laplacian.var()
        
        # Normalize to 0-100 (empirical values)
        # High variance (>100) = sharp, low variance (<10) = blurry
        sharpness_score = min(100, (sharpness_variance / 100) * 100)
        
        # 2. Brightness (mean pixel value)
        brightness = gray.mean()
        
        # Ideal brightness: 80-180, penalty for too dark/bright
        if 80 <= brightness <= 180:
            brightness_score = 100
        elif brightness < 80:
            brightness_score = (brightness / 80) * 100
        else:
            brightness_score = max(0, 100 - ((brightness - 180) / 75) * 100)
        
        # Combined score (weighted average)
        score = (sharpness_score * 0.7) + (brightness_score * 0.3)
        
        return score


class FrameDeduplicator:
    """
    Detect duplicate frames using perceptual hashing
    
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


# Convenience functions for testing
def test_motion_detector():
    """Test motion detector with sample frames"""
    detector = MotionDetector(threshold=5.0)
    
    # Create two similar frames
    frame1 = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    frame2 = frame1.copy()
    
    # No motion (same frame)
    assert detector.has_motion(frame1) == True  # First frame always True
    assert detector.has_motion(frame2) == False
    
    # Motion (different frame)
    frame3 = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    assert detector.has_motion(frame3) == True
    
    print("✓ Motion detector test passed")


def test_quality_scorer():
    """Test quality scorer with sample frames"""
    scorer = QualityScorer(min_score=40.0)
    
    # Create blurry frame (low quality)
    blurry = np.ones((480, 640, 3), dtype=np.uint8) * 128
    blurry = cv2.GaussianBlur(blurry, (51, 51), 0)
    score1 = scorer.score(blurry)
    print(f"Blurry frame score: {score1:.1f}")
    
    # Create sharp frame (high quality)
    sharp = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    score2 = scorer.score(sharp)
    print(f"Sharp frame score: {score2:.1f}")
    
    assert score2 > score1, "Sharp frame should score higher than blurry"
    print("✓ Quality scorer test passed")


def test_deduplicator():
    """Test frame deduplicator with sample frames"""
    dedup = FrameDeduplicator(cache_size=10, threshold=5)
    
    # Create frame
    frame1 = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    
    # First frame is not duplicate
    assert dedup.is_duplicate(frame1) == False
    
    # Same frame is duplicate
    assert dedup.is_duplicate(frame1) == True
    
    # Very similar frame is duplicate
    frame2 = frame1.copy()
    frame2[0:10, 0:10] = 255  # Small change
    assert dedup.is_duplicate(frame2) == True
    
    # Different frame is not duplicate
    frame3 = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    assert dedup.is_duplicate(frame3) == False
    
    print("✓ Deduplicator test passed")


if __name__ == "__main__":
    """Run tests"""
    logging.basicConfig(level=logging.INFO)
    
    print("Running quality filter tests...")
    test_motion_detector()
    test_quality_scorer()
    test_deduplicator()
    print("\n✅ All tests passed!")