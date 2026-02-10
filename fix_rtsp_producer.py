#!/usr/bin/env python3
"""
fix_rtsp_producer.py — แก้ 2 bugs ใน RTSP producer

Bug 1: ImportError — frame_producer.py import "EnhancedQualityFilter" 
       แต่ quality_filter_v2.py มีแค่ "EnhancedQualityScorer"
       
Bug 2: RuntimeWarning — __init__.py import RTSPFrameProducer ทำให้ 
       python -m alpr_worker.rtsp.frame_producer เกิด double-import

วิธีใช้:
    cd thai_lpr_system
    python fix_rtsp_producer.py          # dry-run
    python fix_rtsp_producer.py --apply  # แก้จริง
"""
import argparse
import sys
from pathlib import Path


def find_repo_root():
    for candidate in [Path.cwd(), Path.cwd().parent]:
        if (candidate / "worker").exists():
            return candidate
    print("❌ ไม่พบ repo root")
    sys.exit(1)


ROOT = find_repo_root()
DRY_RUN = True


def patch_file(relpath: str, old: str, new: str, label: str) -> bool:
    fpath = ROOT / relpath
    if not fpath.exists():
        print(f"  ⏭️  {relpath} not found, skip")
        return False

    content = fpath.read_text(encoding="utf-8")
    if old not in content:
        # Check if already patched
        if new in content:
            print(f"  ✅ {relpath} — already patched ({label})")
            return True
        print(f"  ⚠️  {relpath} — pattern not found ({label})")
        return False

    content = content.replace(old, new, 1)
    if not DRY_RUN:
        fpath.write_text(content, encoding="utf-8")
        print(f"  ✅ {relpath} — PATCHED ({label})")
    else:
        print(f"  🔍 {relpath} — would patch ({label})")
    return True


def fix_bug1_import_name():
    """
    Bug 1: frame_producer.py imports "EnhancedQualityFilter" 
    แต่ quality_filter_v2.py define "EnhancedQualityScorer"
    
    แก้ 2 วิธี:
    A) แก้ import ใน frame_producer.py ให้ตรงกับชื่อจริง
    B) เพิ่ม alias ใน quality_filter_v2.py
    
    เลือกวิธี A (แก้ที่ frame_producer.py) เพราะแก้จุดเดียวจบ
    """
    print("\n📝 Bug 1: Fix import name mismatch")

    # Fix import line
    patch_file(
        "worker/alpr_worker/rtsp/frame_producer.py",
        "from alpr_worker.rtsp.quality_filter_v2 import EnhancedQualityFilter",
        "from alpr_worker.rtsp.quality_filter_v2 import EnhancedQualityScorer",
        "fix import name: EnhancedQualityFilter → EnhancedQualityScorer",
    )

    # Fix class reference in _setup_filters
    patch_file(
        "worker/alpr_worker/rtsp/frame_producer.py",
        "if self.enable_night_enhancement and EnhancedQualityFilter:",
        "if self.enable_night_enhancement and EnhancedQualityScorer:",
        "fix class ref in _setup_filters (condition)",
    )

    patch_file(
        "worker/alpr_worker/rtsp/frame_producer.py",
        "self.quality_filter = EnhancedQualityFilter()",
        "self.quality_filter = EnhancedQualityScorer()",
        "fix class ref in _setup_filters (instantiation)",
    )

    # Fix the NIGHT_ENHANCEMENT_AVAILABLE fallback assignment
    patch_file(
        "worker/alpr_worker/rtsp/frame_producer.py",
        "    EnhancedQualityFilter = None",
        "    EnhancedQualityScorer = None",
        "fix fallback None assignment",
    )

    # Also add alias in quality_filter_v2.py for safety (in case other code uses old name)
    patch_file(
        "worker/alpr_worker/rtsp/quality_filter_v2.py",
        "class QualityScorer(EnhancedQualityScorer):\n    \"\"\"Alias for backward compatibility\"\"\"\n    pass",
        "class QualityScorer(EnhancedQualityScorer):\n    \"\"\"Alias for backward compatibility\"\"\"\n    pass\n\n\n# Alias: frame_producer.py เคยใช้ชื่อนี้\nEnhancedQualityFilter = EnhancedQualityScorer",
        "add EnhancedQualityFilter alias in quality_filter_v2.py",
    )


def fix_bug2_init_import():
    """
    Bug 2: __init__.py imports RTSPFrameProducer from frame_producer
    ทำให้ python -m alpr_worker.rtsp.frame_producer เกิด:
      RuntimeWarning: 'alpr_worker.rtsp.frame_producer' found in sys.modules 
      after import of package 'alpr_worker.rtsp', but prior to execution
    
    แก้: เปลี่ยน __init__.py ให้ lazy import RTSPFrameProducer 
    (ลบออกจาก top-level import เพราะ __init__.py ไม่ควร import module ที่อาจรันเป็น __main__)
    """
    print("\n📝 Bug 2: Fix __init__.py double-import RuntimeWarning")

    old_init = """from .frame_producer import RTSPFrameProducer
from .quality_filter import MotionDetector, QualityScorer, FrameDeduplicator
from .config import RTSPConfig
from .roi_zone import ROIZone, ROIConfig

__all__ = [
    "RTSPFrameProducer",
    "MotionDetector",
    "QualityScorer",
    "FrameDeduplicator",
    "RTSPConfig",
    "ROIZone",
    "ROIConfig",
]"""

    new_init = """# NOTE: RTSPFrameProducer ไม่ import ที่นี่เพื่อหลีกเลี่ยง RuntimeWarning
# เมื่อรัน: python -m alpr_worker.rtsp.frame_producer
# ถ้าต้องการใช้ ให้ import ตรงจาก module:
#   from alpr_worker.rtsp.frame_producer import RTSPFrameProducer

from .quality_filter import MotionDetector, QualityScorer, FrameDeduplicator
from .config import RTSPConfig
from .roi_zone import ROIZone, ROIConfig

__all__ = [
    "MotionDetector",
    "QualityScorer",
    "FrameDeduplicator",
    "RTSPConfig",
    "ROIZone",
    "ROIConfig",
]"""

    patch_file(
        "worker/alpr_worker/rtsp/__init__.py",
        old_init,
        new_init,
        "remove RTSPFrameProducer from top-level import",
    )


def fix_bug3_no_gpu_rtsp():
    """
    Bonus: rtsp-producer ไม่ต้อง GPU แต่ใช้ Dockerfile เดียวกับ worker-gpu
    ที่ต้อง nvidia driver → WARNING: The NVIDIA Driver was not detected
    
    นี่ไม่ใช่ bug ที่ต้องแก้ code แต่แนะนำ:
    - rtsp-producer ไม่ได้รัน YOLO/OCR เอง (แค่ capture + enqueue celery task)
    - สามารถใช้ image เบาๆ ได้ แต่ต้องแก้ docker-compose
    """
    print("\n💡 Info: rtsp-producer ไม่ต้อง GPU")
    print("   WARNING 'NVIDIA Driver was not detected' เป็นแค่ warning จาก base image")
    print("   ไม่กระทบการทำงาน เพราะ rtsp-producer ไม่ได้รัน inference")
    print("   (ถ้าจะแก้: สร้าง Dockerfile.rtsp-light ที่ใช้ python:3.11-slim แทน)")


def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="Fix RTSP producer bugs")
    parser.add_argument("--apply", action="store_true", help="Apply patches (default: dry-run)")
    args = parser.parse_args()
    DRY_RUN = not args.apply

    print("🔧 Fix RTSP Producer Issues")
    print(f"   Repo: {ROOT}")
    print(f"   Mode: {'🔍 DRY-RUN' if DRY_RUN else '⚡ APPLY'}")

    fix_bug1_import_name()
    fix_bug2_init_import()
    fix_bug3_no_gpu_rtsp()

    print("\n" + "=" * 60)
    if DRY_RUN:
        print("🔍 Dry-run complete. Run with --apply to patch files.")
    else:
        print("✅ All patches applied!")
        print("   Rebuild: docker compose -f docker-compose.realtime.yml up --build -d rtsp-producer-cam1")


if __name__ == "__main__":
    main()
