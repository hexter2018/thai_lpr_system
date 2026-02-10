"""
Image Preprocessing Module for RTSP Frames

ปรับปรุงภาพก่อนส่งไป YOLO detection:
- Night enhancement (CLAHE)
- Glare reduction (inpainting)
- Auto contrast adjustment
- Noise reduction

Author: Thai ALPR System
Date: 2026-02-09
"""

import cv2
import numpy as np
import logging

log = logging.getLogger(__name__)


def enhance_night_image(image: np.ndarray) -> np.ndarray:
    """
    ปรับปรุงภาพกลางคืนด้วย CLAHE (Contrast Limited Adaptive Histogram Equalization)
    
    ทำงาน:
    1. แปลงเป็น LAB color space
    2. Apply CLAHE ที่ L channel (Lightness)
    3. Merge กลับเป็น BGR
    
    Args:
        image: BGR color image
        
    Returns:
        Enhanced BGR image
    """
    # Convert to LAB color space
    # L = Lightness, A = Green-Red, B = Blue-Yellow
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Apply CLAHE to L channel only
    # clipLimit: ควบคุมการเพิ่ม contrast (สูง = contrast มาก)
    # tileGridSize: ขนาดของ grid สำหรับ local enhancement
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l)
    
    # Merge channels back
    enhanced_lab = cv2.merge([l_enhanced, a, b])
    
    # Convert back to BGR
    enhanced_bgr = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
    
    return enhanced_bgr


def reduce_glare(image: np.ndarray, threshold: int = 240) -> np.ndarray:
    """
    ลดแสงสะท้อน (glare) ด้วย inpainting
    
    ทำงาน:
    1. หาพื้นที่ที่มีแสงสะท้อน (pixels ที่สว่างมาก)
    2. ใช้ inpainting เพื่อ "ซ่อม" พื้นที่นั้น
    
    Args:
        image: BGR color image
        threshold: Brightness threshold for glare detection (0-255)
        
    Returns:
        Glare-reduced BGR image
    """
    # Convert to grayscale for analysis
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Create mask for glare areas (very bright pixels)
    _, glare_mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    
    # Check if there's significant glare
    glare_pixels = np.count_nonzero(glare_mask)
    total_pixels = gray.size
    glare_percentage = (glare_pixels / total_pixels) * 100
    
    # Only apply inpainting if glare > 2% of image
    if glare_percentage < 2.0:
        return image
    
    # Inpaint glare areas
    # INPAINT_TELEA: Fast method based on Fast Marching Method
    # radius=3: Size of neighborhood to consider
    result = cv2.inpaint(image, glare_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    
    log.debug(f"Glare reduction: {glare_percentage:.1f}% of image inpainted")
    
    return result


def denoise_image(image: np.ndarray, strength: int = 10) -> np.ndarray:
    """
    ลด noise ด้วย Non-Local Means Denoising
    
    เหมาะสำหรับ:
    - ภาพกลางคืนที่มี noise สูง
    - ภาพที่มี ISO สูง
    
    Args:
        image: BGR color image
        strength: Denoising strength (higher = more smoothing)
        
    Returns:
        Denoised BGR image
    """
    # fastNlMeansDenoisingColored เหมาะสำหรับภาพสี
    # h: filter strength (10 recommended)
    # templateWindowSize: 7 (ปกติ)
    # searchWindowSize: 21 (ปกติ)
    denoised = cv2.fastNlMeansDenoisingColored(
        image, 
        None, 
        h=strength, 
        hColor=strength, 
        templateWindowSize=7, 
        searchWindowSize=21
    )
    
    return denoised


def auto_contrast(image: np.ndarray) -> np.ndarray:
    """
    ปรับ contrast อัตโนมัติด้วย histogram stretching
    
    Args:
        image: BGR color image
        
    Returns:
        Contrast-adjusted BGR image
    """
    # Convert to YCrCb (Y = brightness)
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    
    # Normalize Y channel (histogram stretching)
    y_min = y.min()
    y_max = y.max()
    
    if y_max > y_min:
        y_normalized = ((y - y_min) / (y_max - y_min) * 255).astype(np.uint8)
    else:
        y_normalized = y
    
    # Merge back
    ycrcb_adjusted = cv2.merge([y_normalized, cr, cb])
    result = cv2.cvtColor(ycrcb_adjusted, cv2.COLOR_YCrCb2BGR)
    
    return result


def sharpen_image(image: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """
    เพิ่มความคมชัดด้วย unsharp masking
    
    Args:
        image: BGR color image
        amount: Sharpening amount (0.0-2.0, 1.0=normal)
        
    Returns:
        Sharpened BGR image
    """
    # Gaussian blur
    blurred = cv2.GaussianBlur(image, (0, 0), 3)
    
    # Unsharp mask = original + amount * (original - blurred)
    sharpened = cv2.addWeighted(image, 1.0 + amount, blurred, -amount, 0)
    
    return sharpened


def auto_enhance(image: np.ndarray, debug: bool = False) -> np.ndarray:
    """
    Auto enhance ตามสภาพภาพ
    
    Pipeline:
    1. ตรวจสอบสภาพภาพ (brightness, glare, contrast)
    2. เลือก preprocessing ที่เหมาะสม
    3. Apply enhancement
    
    Args:
        image: BGR color image
        debug: If True, log enhancement steps
        
    Returns:
        Enhanced BGR image
    """
    if image is None or image.size == 0:
        return image
    
    # Create a copy
    enhanced = image.copy()
    steps_applied = []
    
    # Analyze image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = gray.mean()
    glare_pixels = np.count_nonzero(gray > 240)
    glare_percentage = (glare_pixels / gray.size) * 100
    
    # Calculate contrast
    min_val = gray.min()
    max_val = gray.max()
    if max_val + min_val > 0:
        contrast = ((max_val - min_val) / (max_val + min_val)) * 100
    else:
        contrast = 0.0
    
    # 1. Night enhancement (brightness < 80)
    if brightness < 80:
        enhanced = enhance_night_image(enhanced)
        steps_applied.append("night_enhance")
        
        # Additional denoising for very dark images
        if brightness < 50:
            enhanced = denoise_image(enhanced, strength=10)
            steps_applied.append("denoise")
    
    # 2. Glare reduction (> 5% of image is over-exposed)
    elif glare_percentage > 5.0:
        enhanced = reduce_glare(enhanced, threshold=240)
        steps_applied.append("glare_reduce")
    
    # 3. Low contrast enhancement (contrast < 30)
    if contrast < 30:
        enhanced = auto_contrast(enhanced)
        steps_applied.append("auto_contrast")
    
    # 4. Sharpening (only if not too dark)
    if brightness > 50:
        # Mild sharpening for plate clarity
        enhanced = sharpen_image(enhanced, amount=0.5)
        steps_applied.append("sharpen")
    
    # Debug logging
    if debug and steps_applied:
        log.info(
            f"Auto-enhance applied: {', '.join(steps_applied)} "
            f"(brightness={brightness:.1f}, glare={glare_percentage:.1f}%, "
            f"contrast={contrast:.1f})"
        )
    
    return enhanced


def preprocess_for_detection(image: np.ndarray) -> np.ndarray:
    """
    Preprocess สำหรับ YOLO detection โดยเฉพาะ
    
    Optimized pipeline:
    1. Auto enhance ตามสภาพภาพ
    2. Resize ถ้าจำเป็น (เพื่อ performance)
    3. Normalize
    
    Args:
        image: BGR color image
        
    Returns:
        Preprocessed BGR image ready for detection
    """
    # Auto enhance
    enhanced = auto_enhance(image, debug=False)
    
    # Optional: Resize if image is very large (> 2000px)
    # เพื่อลด memory และเพิ่ม speed
    h, w = enhanced.shape[:2]
    max_dim = 2000
    
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        enhanced = cv2.resize(enhanced, (new_w, new_h), interpolation=cv2.INTER_AREA)
        log.debug(f"Resized image from {w}x{h} to {new_w}x{new_h}")
    
    return enhanced


# ===== Testing Functions =====

def test_night_enhancement():
    """Test night enhancement"""
    print("Testing night enhancement...")
    
    # Create synthetic night image
    night = np.ones((480, 640, 3), dtype=np.uint8) * 40
    night[200:280, 300:340] = [200, 200, 200]  # Car headlights
    
    enhanced = enhance_night_image(night)
    
    # Check that enhancement increased brightness
    night_brightness = cv2.cvtColor(night, cv2.COLOR_BGR2GRAY).mean()
    enhanced_brightness = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY).mean()
    
    assert enhanced_brightness > night_brightness
    print(f"  Night brightness: {night_brightness:.1f} → {enhanced_brightness:.1f} ✓")


def test_glare_reduction():
    """Test glare reduction"""
    print("Testing glare reduction...")
    
    # Create image with glare
    glare_img = np.ones((480, 640, 3), dtype=np.uint8) * 128
    glare_img[100:200, 200:400] = 255  # Glare area (10% of image)
    
    reduced = reduce_glare(glare_img)
    
    # Check that glare pixels are reduced
    gray_before = cv2.cvtColor(glare_img, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(reduced, cv2.COLOR_BGR2GRAY)
    
    glare_before = np.count_nonzero(gray_before > 240)
    glare_after = np.count_nonzero(gray_after > 240)
    
    assert glare_after < glare_before
    print(f"  Glare pixels: {glare_before} → {glare_after} ✓")


def test_auto_enhance():
    """Test auto enhance"""
    print("Testing auto enhance...")
    
    # Test 1: Night image
    night = np.ones((480, 640, 3), dtype=np.uint8) * 50
    night_enhanced = auto_enhance(night, debug=True)
    assert night_enhanced is not None
    print("  Night image: ✓")
    
    # Test 2: Normal image
    normal = np.ones((480, 640, 3), dtype=np.uint8) * 150
    normal_enhanced = auto_enhance(normal, debug=True)
    assert normal_enhanced is not None
    print("  Normal image: ✓")
    
    # Test 3: Glare image
    glare = np.ones((480, 640, 3), dtype=np.uint8) * 250
    glare_enhanced = auto_enhance(glare, debug=True)
    assert glare_enhanced is not None
    print("  Glare image: ✓")


if __name__ == "__main__":
    """Run tests"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Image Preprocessing Tests")
    print("=" * 60)
    print()
    
    test_night_enhancement()
    test_glare_reduction()
    test_auto_enhance()
    
    print()
    print("=" * 60)
    print("✅ All preprocessing tests passed!")
    print("=" * 60)