#!/usr/bin/env python3
"""
apply_patches.py — Auto-apply Enhanced RTSP patches to Thai ALPR repo

วิธีใช้:
    cd thai_lpr_system
    python apply_patches.py

จะแก้ไขไฟล์เดิม + สร้างไฟล์ใหม่ อัตโนมัติ
⚠️ แนะนำ: git commit ก่อนรัน เพื่อสามารถ revert ได้
"""
import os
import re
import sys
import shutil
from pathlib import Path


def find_repo_root():
    """หา repo root (มี docker-compose.yml)"""
    for candidate in [Path.cwd(), Path.cwd().parent]:
        if (candidate / "docker-compose.yml").exists() and (candidate / "worker").exists():
            return candidate
    print("❌ ไม่พบ repo root (ต้องรันจาก thai_lpr_system directory)")
    sys.exit(1)


ROOT = find_repo_root()
WORKER = ROOT / "worker"


# ================================================================
# Patch 1: สร้างไฟล์ใหม่ roi_zone.py
# ================================================================
def patch_roi_zone():
    """สร้าง worker/alpr_worker/rtsp/roi_zone.py"""
    target = WORKER / "alpr_worker" / "rtsp" / "roi_zone.py"
    if target.exists():
        print(f"  ⏭️ {target.relative_to(ROOT)} already exists, skipping")
        return

    # Check if roi_zone.py อยู่ใน directory เดียวกับ script
    source = Path(__file__).parent / "roi_zone.py"
    if source.exists():
        shutil.copy2(source, target)
        print(f"  ✅ Created {target.relative_to(ROOT)} (copied from {source.name})")
    else:
        print(f"  ❌ roi_zone.py not found next to this script. Please copy it manually.")
        print(f"     Target: {target}")


# ================================================================
# Patch 2: แก้ config.py — เพิ่ม ROI fields
# ================================================================
def patch_config():
    """เพิ่ม ROI config fields ใน RTSPConfig"""
    target = WORKER / "alpr_worker" / "rtsp" / "config.py"
    content = target.read_text(encoding="utf-8")

    if "roi_x1" in content:
        print(f"  ⏭️ {target.relative_to(ROOT)} already patched")
        return

    # เพิ่ม fields ใน dataclass (หลัง dedup_threshold)
    old = '    dedup_threshold: int = 5  # Hamming distance'
    new = '''    dedup_threshold: int = 5  # Hamming distance
    
    # ROI Zone
    roi_enabled: bool = True
    roi_x1: float = 0.0
    roi_y1: float = 0.15
    roi_x2: float = 1.0
    roi_y2: float = 0.90'''

    if old not in content:
        print(f"  ⚠️ Cannot find anchor in config.py, manual patch needed")
        return

    content = content.replace(old, new, 1)

    # เพิ่มใน from_env()
    old_env = '            dedup_threshold=int(os.getenv("RTSP_DEDUP_THRESHOLD", "5")),'
    new_env = '''            dedup_threshold=int(os.getenv("RTSP_DEDUP_THRESHOLD", "5")),
            
            # ROI Zone
            roi_enabled=os.getenv("RTSP_ROI_ENABLED", "true").lower() == "true",
            roi_x1=float(os.getenv("RTSP_ROI_X1", "0.0")),
            roi_y1=float(os.getenv("RTSP_ROI_Y1", "0.15")),
            roi_x2=float(os.getenv("RTSP_ROI_X2", "1.0")),
            roi_y2=float(os.getenv("RTSP_ROI_Y2", "0.90")),'''

    if old_env in content:
        content = content.replace(old_env, new_env, 1)

    # เพิ่มใน __str__
    old_str = '  Deduplication: {self.enable_dedup} (cache={self.dedup_cache_size}, threshold={self.dedup_threshold})'
    new_str = '''  Deduplication: {self.enable_dedup} (cache={self.dedup_cache_size}, threshold={self.dedup_threshold})
  ROI Zone: {self.roi_enabled} ({self.roi_x1}, {self.roi_y1}) -> ({self.roi_x2}, {self.roi_y2})'''

    if old_str in content:
        content = content.replace(old_str, new_str, 1)

    target.write_text(content, encoding="utf-8")
    print(f"  ✅ Patched {target.relative_to(ROOT)}")


# ================================================================
# Patch 3: แก้ best_shot.py — ปรับ scoring weights
# ================================================================
def patch_best_shot():
    """ปรับ scoring formula ใน BestShotSelector"""
    target = WORKER / "alpr_worker" / "rtsp" / "best_shot.py"
    content = target.read_text(encoding="utf-8")

    if "0.12 * area_norm" in content:
        print(f"  ⏭️ {target.relative_to(ROOT)} already patched")
        return

    old_score = '''        # น้ำหนักเน้น OCR ก่อน -> ลดอ่านผิด
        return (0.55 * ocr_conf) + (0.15 * det_conf) + (0.15 * sharp_norm) + (0.10 * q_norm) + (0.05 * area_norm)'''

    new_score = '''        # น้ำหนักปรับปรุง: เพิ่ม area (ป้ายใหญ่=อ่านง่าย) + sharpness (คมชัด=OCR แม่น)
        return (
            0.45 * ocr_conf
            + 0.15 * det_conf
            + 0.18 * sharp_norm
            + 0.10 * q_norm
            + 0.12 * area_norm
        )'''

    if old_score not in content:
        print(f"  ⚠️ Cannot find scoring formula in best_shot.py, manual patch needed")
        return

    # ปรับ area_norm threshold ด้วย
    content = content.replace("area_norm = min(1.0, plate_area_ratio / 0.08)", 
                               "area_norm = min(1.0, plate_area_ratio / 0.06)")
    content = content.replace(old_score, new_score, 1)

    target.write_text(content, encoding="utf-8")
    print(f"  ✅ Patched {target.relative_to(ROOT)}")


# ================================================================
# Patch 4: แก้ frame_producer.py — integrate ROI
# ================================================================
def patch_frame_producer():
    """เพิ่ม ROI integration ใน RTSPFrameProducer"""
    target = WORKER / "alpr_worker" / "rtsp" / "frame_producer.py"
    content = target.read_text(encoding="utf-8")

    if "roi_zone" in content:
        print(f"  ⏭️ {target.relative_to(ROOT)} already patched")
        return

    # 4.1 เพิ่ม import
    old_import = "from alpr_worker.rtsp.best_shot import BestShotSelector, norm_plate_text"
    new_import = """from alpr_worker.rtsp.best_shot import BestShotSelector, norm_plate_text
from alpr_worker.rtsp.roi_zone import ROIZone, ROIConfig"""

    if old_import in content:
        content = content.replace(old_import, new_import, 1)

    # 4.2 เพิ่ม ROI init (หลัง _setup_filters)
    old_init = "        # -------- Best-shot (1 car = 1 best image) --------"
    new_init = """        # -------- ROI Zone --------
        if getattr(self.config, 'roi_enabled', True):
            roi_cfg = ROIConfig(
                x1=getattr(self.config, 'roi_x1', 0.0),
                y1=getattr(self.config, 'roi_y1', 0.15),
                x2=getattr(self.config, 'roi_x2', 1.0),
                y2=getattr(self.config, 'roi_y2', 0.90),
            )
            self.roi_zone = ROIZone(roi_cfg)
        else:
            self.roi_zone = None

        # -------- Best-shot (1 car = 1 best image) --------"""

    if old_init in content:
        content = content.replace(old_init, new_init, 1)

    # 4.3 เพิ่ม ROI crop ก่อน detect (ใน best-shot mode)
    old_detect = """                # 1) save candidate
                tmp_path = self._save_frame(frame_to_use)

                # 2) detect + crop plate
                det = self.detector.detect_and_crop(tmp_path)"""

    new_detect = """                # 0) ROI crop (ตัดพื้นที่ไม่จำเป็นออก → เร็วขึ้น + ลด false positive)
                roi_frame = frame_to_use
                if self.roi_zone and self.roi_zone.enabled:
                    roi_frame, _roi_offset = self.roi_zone.crop(frame_to_use)

                # 1) save ROI-cropped candidate
                tmp_path = self._save_frame(roi_frame)

                # 2) detect + crop plate (ทำงานบน ROI frame ที่เล็กลง)
                det = self.detector.detect_and_crop(tmp_path)"""

    if old_detect in content:
        content = content.replace(old_detect, new_detect, 1)

    target.write_text(content, encoding="utf-8")
    print(f"  ✅ Patched {target.relative_to(ROOT)}")


# ================================================================
# Patch 5: แก้ __init__.py — เพิ่ม ROI exports
# ================================================================
def patch_rtsp_init():
    """เพิ่ม ROI imports ใน rtsp __init__"""
    target = WORKER / "alpr_worker" / "rtsp" / "__init__.py"
    content = target.read_text(encoding="utf-8")

    if "ROIZone" in content:
        print(f"  ⏭️ {target.relative_to(ROOT)} already patched")
        return

    old = '''from .config import RTSPConfig

__all__ = [
    "RTSPFrameProducer",
    "MotionDetector",
    "QualityScorer",
    "FrameDeduplicator",
    "RTSPConfig",
]'''

    new = '''from .config import RTSPConfig
from .roi_zone import ROIZone, ROIConfig

__all__ = [
    "RTSPFrameProducer",
    "MotionDetector",
    "QualityScorer",
    "FrameDeduplicator",
    "RTSPConfig",
    "ROIZone",
    "ROIConfig",
]'''

    if old in content:
        content = content.replace(old, new, 1)
        target.write_text(content, encoding="utf-8")
        print(f"  ✅ Patched {target.relative_to(ROOT)}")
    else:
        print(f"  ⚠️ Cannot find anchor in __init__.py, manual patch needed")


# ================================================================
# Patch 6: แก้ ocr.py — เพิ่ม deskew + sharpen variants
# ================================================================
def patch_ocr():
    """เพิ่ม deskew + sharpen variants ใน PlateOCR"""
    target = WORKER / "alpr_worker" / "inference" / "ocr.py"
    content = target.read_text(encoding="utf-8")

    if "_deskew_plate" in content:
        print(f"  ⏭️ {target.relative_to(ROOT)} already patched")
        return

    # 6.1 อัพเดท default variant names
    old_names = '''_DEFAULT_VARIANT_NAMES = (
    "gray",
    "clahe",
    "adaptive",
    "otsu",
    "upscale_x2",
    "upscale_adaptive_x2",
    "upscale_otsu_x2",
)
_DEFAULT_VARIANT_LIMIT = len(_DEFAULT_VARIANT_NAMES)'''

    new_names = '''_DEFAULT_VARIANT_NAMES = (
    "gray",
    "clahe",
    "adaptive",
    "otsu",
    "deskew",
    "sharpen",
    "upscale_x2",
    "upscale_adaptive_x2",
    "upscale_otsu_x2",
)
_DEFAULT_VARIANT_LIMIT = len(_DEFAULT_VARIANT_NAMES)'''

    if old_names in content:
        content = content.replace(old_names, new_names, 1)

    # 6.2 เพิ่ม deskew + sharpen variants ใน _build_variants
    old_variants = '''        up3 = cv2.resize(clahe, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

        variants = [
            ("gray", gray),
            ("clahe", clahe),
            ("adaptive", adaptive),
            ("otsu", otsu),
            ("green_mask", green_inv),
            ("upscale_x2", up2),'''

    new_variants = '''        up3 = cv2.resize(clahe, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

        # Deskew: แก้ป้ายเอียงจาก perspective ของกล้อง
        deskewed = self._deskew_plate(gray)

        # Sharpen: เพิ่มขอบตัวอักษรให้ชัดขึ้น
        _sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
        sharpened = cv2.filter2D(clahe, -1, _sharpen_kernel)

        variants = [
            ("gray", gray),
            ("clahe", clahe),
            ("adaptive", adaptive),
            ("otsu", otsu),
            ("green_mask", green_inv),
            ("deskew", deskewed),
            ("sharpen", sharpened),
            ("upscale_x2", up2),'''

    if old_variants in content:
        content = content.replace(old_variants, new_variants, 1)

    # 6.3 เพิ่ม _deskew_plate method (หลัง _topline_roi_pass)
    # หาจุดแทรกที่เหมาะสม
    insert_anchor = "    def _province_roi_pass(self, image: np.ndarray) -> Dict[str, Any]:"
    deskew_method = '''    def _deskew_plate(self, gray: np.ndarray) -> np.ndarray:
        """แก้ภาพป้ายเอียงด้วย Hough Line detection"""
        try:
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 50,
                                     minLineLength=30, maxLineGap=10)
            if lines is None or len(lines) == 0:
                return gray

            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if abs(x2 - x1) > 5:
                    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    if abs(angle) < 30:
                        angles.append(angle)

            if not angles:
                return gray

            median_angle = float(np.median(angles))
            if abs(median_angle) < 0.5:
                return gray

            h, w = gray.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            rotated = cv2.warpAffine(gray, M, (w, h),
                                      flags=cv2.INTER_CUBIC,
                                      borderMode=cv2.BORDER_REPLICATE)
            return rotated
        except Exception:
            return gray

'''

    if insert_anchor in content and "_deskew_plate" not in content:
        content = content.replace(insert_anchor, deskew_method + "    " + insert_anchor)

    target.write_text(content, encoding="utf-8")
    print(f"  ✅ Patched {target.relative_to(ROOT)}")


# ================================================================
# Main
# ================================================================
def main():
    print("=" * 60)
    print("🔧 Enhanced RTSP Patch Applier — Thai ALPR System")
    print(f"   Repo root: {ROOT}")
    print("=" * 60)
    print()

    patches = [
        ("1. ROI Zone module (new file)", patch_roi_zone),
        ("2. Config — ROI fields", patch_config),
        ("3. Best-shot — scoring weights", patch_best_shot),
        ("4. Frame producer — ROI integration", patch_frame_producer),
        ("5. RTSP __init__ — exports", patch_rtsp_init),
        ("6. OCR — deskew + sharpen variants", patch_ocr),
    ]

    for name, func in patches:
        print(f"📦 {name}")
        try:
            func()
        except Exception as e:
            print(f"  ❌ Error: {e}")
        print()

    print("=" * 60)
    print("✅ Patching complete!")
    print()
    print("Next steps:")
    print("  1. ตรวจสอบ git diff เพื่อ review changes")
    print("  2. ตั้งค่า ROI ใน docker-compose.realtime.yml:")
    print("     RTSP_ROI_ENABLED=true")
    print("     RTSP_ROI_X1=0.05  RTSP_ROI_Y1=0.15")
    print("     RTSP_ROI_X2=0.95  RTSP_ROI_Y2=0.90")
    print("  3. docker compose -f docker-compose.realtime.yml up --build")
    print("=" * 60)


if __name__ == "__main__":
    main()
