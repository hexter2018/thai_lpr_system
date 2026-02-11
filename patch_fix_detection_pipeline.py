#!/usr/bin/env python3
"""
patch_fix_detection_pipeline.py — แก้ปัญหา "No plate detected" 100%
=====================================================================

สาเหตุที่พบจากการ review code ทั้งโปรเจก:

🚨 BUG 1: HeadlightDeglare ไม่ได้ integrate เข้า tasks.py (GPU worker)
   - deglare.py มีอยู่แล้วใน /rtsp/ แต่ไม่เคยถูกเรียกใน process_capture task
   - ภาพกลางคืนมี headlight glare → YOLO detect ไม่เจอ
   - FIX: เพิ่ม deglare preprocessing ก่อน YOLO + dual detection strategy

🚨 BUG 2: DEGLARE env vars อยู่ผิด container (อยู่ใน flower แทน worker-gpu-1)
   - FIX: ย้ายไป worker-gpu-1

🚨 BUG 3: detect_and_crop ไม่มี fallback (ลองครั้งเดียว ไม่เจอ = จบ)
   - FIX: dual detection — ลอง deglared ก่อน, ถ้าไม่เจอลอง original

Usage:
    python patch_fix_detection_pipeline.py --check     # ดูว่าต้องแก้อะไร
    python patch_fix_detection_pipeline.py --apply      # apply patches
    python patch_fix_detection_pipeline.py --dry-run    # ดู diff ก่อน apply
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime


def find_project_root() -> Path:
    """Find thai_lpr_system project root"""
    candidates = [
        Path.cwd(),
        Path.cwd() / "thai_lpr_system",
        Path("/app"),
        Path.home() / "thai_lpr_system",
    ]
    for c in candidates:
        if (c / "worker" / "alpr_worker" / "tasks.py").exists():
            return c
        if (c / "docker-compose.realtime.yml").exists():
            return c
    return Path.cwd()


class PipelineFixer:
    def __init__(self, root: Path, dry_run: bool = False):
        self.root = root
        self.dry_run = dry_run
        self.changes = []
        self.warnings = []

    def check(self):
        """Check all issues"""
        print("=" * 70)
        print("🔍 PIPELINE DIAGNOSIS")
        print("=" * 70)
        
        issues = []
        
        # Issue 1: Deglare not in tasks.py
        tasks_path = self.root / "worker" / "alpr_worker" / "tasks.py"
        if tasks_path.exists():
            content = tasks_path.read_text()
            if "deglare" not in content.lower() and "HeadlightDeglare" not in content:
                issues.append({
                    "severity": "CRITICAL",
                    "file": "worker/alpr_worker/tasks.py",
                    "issue": "HeadlightDeglare ไม่ได้ integrate เข้า process_capture task",
                    "impact": "ภาพกลางคืนมี headlight glare → YOLO detect ไม่เจอ 100%",
                    "fix": "เพิ่ม deglare preprocessing + dual detection",
                })
            else:
                print("  ✅ tasks.py: deglare already integrated")
        
        # Issue 2: DEGLARE env in wrong container
        compose_path = self.root / "docker-compose.realtime.yml"
        if compose_path.exists():
            content = compose_path.read_text()
            
            # Check if DEGLARE is under flower instead of worker-gpu-1
            # Simple heuristic: find DEGLARE_ENABLED and check context
            flower_section = self._extract_service_section(content, "flower")
            worker_section = self._extract_service_section(content, "worker-gpu-1")
            
            if flower_section and "DEGLARE_ENABLED" in flower_section:
                issues.append({
                    "severity": "CRITICAL",
                    "file": "docker-compose.realtime.yml",
                    "issue": "DEGLARE env vars อยู่ใน flower container (ไม่ใช่ worker-gpu-1)",
                    "impact": "GPU worker ไม่เห็น DEGLARE config → deglare ไม่ทำงาน",
                    "fix": "ย้าย DEGLARE_* จาก flower ไป worker-gpu-1",
                })
            
            if worker_section and "DEGLARE_ENABLED" not in worker_section:
                issues.append({
                    "severity": "CRITICAL", 
                    "file": "docker-compose.realtime.yml",
                    "issue": "worker-gpu-1 ไม่มี DEGLARE env vars",
                    "impact": "GPU worker ไม่มี deglare config",
                    "fix": "เพิ่ม DEGLARE_* ใน worker-gpu-1 environment",
                })
            
        # Issue 3: No ROI cropping before YOLO in tasks.py
        if tasks_path.exists():
            content = tasks_path.read_text()
            if "roi" not in content.lower() and "ROIZone" not in content:
                issues.append({
                    "severity": "MEDIUM",
                    "file": "worker/alpr_worker/tasks.py",
                    "issue": "ROI cropping ไม่ได้ใช้ใน GPU worker",
                    "impact": "YOLO ต้อง scan ทั้งภาพ (รวม sky, road ที่ไม่มีป้าย)",
                    "fix": "เพิ่ม optional ROI crop ก่อน YOLO (ไม่จำเป็นถ้า model ดี)",
                })
        
        # Issue 4: deglare.py location
        deglare_rtsp = self.root / "worker" / "alpr_worker" / "rtsp" / "deglare.py"
        deglare_inference = self.root / "worker" / "alpr_worker" / "inference" / "deglare.py"
        if deglare_rtsp.exists() and not deglare_inference.exists():
            issues.append({
                "severity": "HIGH",
                "file": "worker/alpr_worker/inference/deglare.py",
                "issue": "deglare.py อยู่ใน rtsp/ (producer) แต่ต้องใช้ใน inference/ (GPU worker)",
                "impact": "import path ผิด ถ้า tasks.py พยายาม import",
                "fix": "Copy deglare.py ไป inference/ ด้วย หรือ import จาก rtsp/",
            })

        # Print results
        if not issues:
            print("\n  ✅ ไม่พบปัญหา — pipeline ควรทำงานได้ปกติ")
            print("  ถ้ายังเจอ 'No plate detected' อาจเป็นเรื่อง:")
            print("  - Model ไม่เหมาะกับภาพกลางคืน (ต้อง retrain)")
            print("  - ภาพมืดเกินไปจริงๆ (ไม่มี plate visible แม้แต่ตาคน)")
            return []
        
        for i, issue in enumerate(issues, 1):
            sev_icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(issue["severity"], "⚪")
            print(f"\n  {sev_icon} Issue #{i}: [{issue['severity']}]")
            print(f"     File:   {issue['file']}")
            print(f"     Issue:  {issue['issue']}")
            print(f"     Impact: {issue['impact']}")
            print(f"     Fix:    {issue['fix']}")
        
        print(f"\n  Total: {len(issues)} issues found")
        return issues

    def _extract_service_section(self, compose_content: str, service_name: str) -> str:
        """Extract a service section from docker-compose content (rough)"""
        lines = compose_content.split("\n")
        in_service = False
        indent = 0
        section = []
        
        for line in lines:
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)
            
            if stripped.startswith(f"{service_name}:"):
                in_service = True
                indent = current_indent
                section.append(line)
                continue
            
            if in_service:
                if stripped and current_indent <= indent and not stripped.startswith("#"):
                    # New service at same or lower indent
                    break
                section.append(line)
        
        return "\n".join(section)

    def apply(self):
        """Apply all fixes"""
        print("=" * 70)
        print("🔧 APPLYING FIXES")
        print("=" * 70)
        
        self._fix_tasks_py()
        self._fix_docker_compose()
        self._ensure_deglare_accessible()
        
        print("\n" + "=" * 70)
        print(f"✅ Applied {len(self.changes)} changes")
        for c in self.changes:
            print(f"   • {c}")
        
        if self.warnings:
            print(f"\n⚠️  {len(self.warnings)} warnings:")
            for w in self.warnings:
                print(f"   • {w}")
        
        print("\n📋 NEXT STEPS:")
        print("   1. cd thai_lpr_system")
        print("   2. docker compose -f docker-compose.realtime.yml up --build -d")
        print("   3. ดู log: docker compose -f docker-compose.realtime.yml logs -f worker-gpu-1")
        print("   4. ดู log: docker compose -f docker-compose.realtime.yml logs -f rtsp-producer-cam1")

    def _backup(self, path: Path):
        """Backup file before modifying"""
        if path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = path.with_suffix(f".bak_{ts}")
            if not self.dry_run:
                shutil.copy2(path, backup)

    # ================================================================
    # FIX 1: Integrate deglare into tasks.py
    # ================================================================
    def _fix_tasks_py(self):
        """Add deglare preprocessing to process_capture task"""
        tasks_path = self.root / "worker" / "alpr_worker" / "tasks.py"
        if not tasks_path.exists():
            self.warnings.append(f"tasks.py not found at {tasks_path}")
            return
        
        content = tasks_path.read_text()
        
        # Check if already patched
        if "HeadlightDeglare" in content or "deglare" in content.lower():
            print("  ✅ tasks.py: deglare already integrated, skipping")
            return
        
        self._backup(tasks_path)
        
        # --- Patch 1: Add import for deglare ---
        old_import = "from .inference.detector import PlateDetector"
        new_import = """from .inference.detector import PlateDetector

# --- Headlight Deglare (ลด glare จากไฟหน้ารถกลางคืน) ---
try:
    from .rtsp.deglare import HeadlightDeglare
    _deglare: Optional[HeadlightDeglare] = None
    DEGLARE_AVAILABLE = True
except ImportError:
    DEGLARE_AVAILABLE = False
    _deglare = None
    log.warning("HeadlightDeglare not available (deglare.py not found)")


def get_deglare() -> Optional["HeadlightDeglare"]:
    global _deglare
    if not DEGLARE_AVAILABLE:
        return None
    if _deglare is None:
        _deglare = HeadlightDeglare()
    return _deglare"""

        if old_import in content:
            content = content.replace(old_import, new_import)
        else:
            self.warnings.append("Could not find import anchor for deglare in tasks.py")
            return

        # --- Patch 2: Replace the detect section in process_capture ---
        # Find the detection block and replace with dual detection
        old_detect = """        # 1) detect + crop
        det = detector.detect_and_crop(str(img_path))
        crop_path = det.crop_path"""

        new_detect = """        # 1) detect + crop (with optional deglare preprocessing)
        det = None
        crop_path = None
        
        # Try deglare preprocessing first (helps with nighttime headlight glare)
        deglare = get_deglare()
        if deglare:
            try:
                import cv2 as _cv2
                frame = _cv2.imread(str(img_path))
                if frame is not None:
                    processed, original = deglare.process_for_detection(frame)
                    
                    if original is not None:
                        # Deglare changed the image — try processed version first
                        deglared_path = str(img_path) + ".deglared.jpg"
                        _cv2.imwrite(deglared_path, processed)
                        try:
                            det = detector.detect_and_crop(deglared_path)
                            crop_path = det.crop_path
                            log.info("✅ Deglare helped: plate detected after preprocessing")
                        except RuntimeError:
                            # Deglared version failed, try original
                            try:
                                det = detector.detect_and_crop(str(img_path))
                                crop_path = det.crop_path
                            except RuntimeError:
                                pass  # Both failed
                        finally:
                            # Cleanup temp file
                            try:
                                Path(deglared_path).unlink(missing_ok=True)
                            except Exception:
                                pass
                    else:
                        # No deglare needed (no significant glare)
                        det = detector.detect_and_crop(str(img_path))
                        crop_path = det.crop_path
            except RuntimeError:
                # Deglare path failed completely, will be caught below
                pass
            except Exception as e:
                log.warning("Deglare preprocessing error: %s", e)
        
        # Fallback: try without deglare
        if det is None:
            det = detector.detect_and_crop(str(img_path))
            crop_path = det.crop_path"""

        if old_detect in content:
            content = content.replace(old_detect, new_detect)
        else:
            # Try a more flexible match
            old_detect_alt = "det = detector.detect_and_crop(str(img_path))"
            if old_detect_alt in content:
                # Find the line and its context
                lines = content.split("\n")
                new_lines = []
                replaced = False
                for i, line in enumerate(lines):
                    if not replaced and old_detect_alt in line and "deglare" not in line:
                        indent = " " * (len(line) - len(line.lstrip()))
                        new_lines.append(f"{indent}# 1) detect + crop (with deglare preprocessing)")
                        new_lines.append(f"{indent}det = None")
                        new_lines.append(f"{indent}crop_path = None")
                        new_lines.append(f"{indent}")
                        new_lines.append(f"{indent}deglare = get_deglare()")
                        new_lines.append(f"{indent}if deglare:")
                        new_lines.append(f"{indent}    try:")
                        new_lines.append(f"{indent}        import cv2 as _cv2")
                        new_lines.append(f"{indent}        frame = _cv2.imread(str(img_path))")
                        new_lines.append(f"{indent}        if frame is not None:")
                        new_lines.append(f"{indent}            processed, original = deglare.process_for_detection(frame)")
                        new_lines.append(f"{indent}            if original is not None:")
                        new_lines.append(f"{indent}                deglared_path = str(img_path) + '.deglared.jpg'")
                        new_lines.append(f"{indent}                _cv2.imwrite(deglared_path, processed)")
                        new_lines.append(f"{indent}                try:")
                        new_lines.append(f"{indent}                    det = detector.detect_and_crop(deglared_path)")
                        new_lines.append(f"{indent}                    crop_path = det.crop_path")
                        new_lines.append(f"{indent}                    log.info('Deglare helped: plate detected after preprocessing')")
                        new_lines.append(f"{indent}                except RuntimeError:")
                        new_lines.append(f"{indent}                    pass")
                        new_lines.append(f"{indent}                finally:")
                        new_lines.append(f"{indent}                    try:")
                        new_lines.append(f"{indent}                        Path(deglared_path).unlink(missing_ok=True)")
                        new_lines.append(f"{indent}                    except Exception:")
                        new_lines.append(f"{indent}                        pass")
                        new_lines.append(f"{indent}    except Exception as e:")
                        new_lines.append(f"{indent}        log.warning('Deglare error: %s', e)")
                        new_lines.append(f"{indent}")
                        new_lines.append(f"{indent}if det is None:")
                        new_lines.append(f"{indent}    det = detector.detect_and_crop(str(img_path))")
                        new_lines.append(f"{indent}    crop_path = det.crop_path")
                        replaced = True
                        # Skip the next line if it's "crop_path = det.crop_path"
                        if i + 1 < len(lines) and "crop_path = det.crop_path" in lines[i + 1]:
                            continue
                    else:
                        new_lines.append(line)
                content = "\n".join(new_lines)
            else:
                self.warnings.append("Could not find detect_and_crop call in tasks.py — manual edit needed")
                return

        if not self.dry_run:
            tasks_path.write_text(content)
        
        self.changes.append("tasks.py: Added HeadlightDeglare preprocessing with dual detection")
        print("  ✅ tasks.py: Deglare + dual detection integrated")

    # ================================================================
    # FIX 2: Fix docker-compose.realtime.yml
    # ================================================================
    def _fix_docker_compose(self):
        """Move DEGLARE env from flower to worker-gpu-1"""
        compose_path = self.root / "docker-compose.realtime.yml"
        if not compose_path.exists():
            self.warnings.append(f"docker-compose.realtime.yml not found at {compose_path}")
            return
        
        self._backup(compose_path)
        content = compose_path.read_text()
        original = content
        
        # Remove DEGLARE env from flower section
        # Pattern: lines with DEGLARE_* under flower's environment
        lines = content.split("\n")
        new_lines = []
        in_flower = False
        flower_indent = 0
        removed_from_flower = []
        
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)
            
            if stripped.startswith("flower:"):
                in_flower = True
                flower_indent = current_indent
            elif in_flower and stripped and current_indent <= flower_indent and not stripped.startswith("#"):
                in_flower = False
            
            if in_flower and stripped.startswith("DEGLARE_"):
                removed_from_flower.append(stripped)
                continue  # Skip this line
            
            new_lines.append(line)
        
        content = "\n".join(new_lines)
        
        if removed_from_flower:
            self.changes.append(f"docker-compose: Removed {len(removed_from_flower)} DEGLARE vars from flower")
            print(f"  ✅ Removed DEGLARE vars from flower: {removed_from_flower}")
        
        # Add DEGLARE env to worker-gpu-1 if not present
        if "DEGLARE_ENABLED" not in self._extract_service_section(content, "worker-gpu-1"):
            # Find the right place to insert (after MASTER_CONF_THRESHOLD in worker-gpu-1)
            marker = 'MASTER_CONF_THRESHOLD: "0.95"'
            if marker in content:
                deglare_envs = '''MASTER_CONF_THRESHOLD: "0.95"
      
      # Headlight Deglare (preprocessing ก่อน YOLO สำหรับภาพกลางคืน)
      DEGLARE_ENABLED: "true"
      DEGLARE_SATURATION_THRESHOLD: "240"
      DEGLARE_CLAHE_CLIP: "3.0"'''
                content = content.replace(marker, deglare_envs)
                self.changes.append("docker-compose: Added DEGLARE env vars to worker-gpu-1")
                print("  ✅ Added DEGLARE env vars to worker-gpu-1")
            else:
                # Fallback: try different marker
                marker2 = "CELERY_WORKER_CONCURRENCY"
                if marker2 in content:
                    # Insert before celery settings
                    idx = content.index(marker2)
                    # Find the line start
                    line_start = content.rfind("\n", 0, idx) + 1
                    indent = " " * 6
                    insert = (
                        f"\n{indent}# Headlight Deglare\n"
                        f'{indent}DEGLARE_ENABLED: "true"\n'
                        f'{indent}DEGLARE_SATURATION_THRESHOLD: "240"\n'
                        f'{indent}DEGLARE_CLAHE_CLIP: "3.0"\n'
                    )
                    content = content[:line_start] + insert + content[line_start:]
                    self.changes.append("docker-compose: Added DEGLARE env vars to worker-gpu-1")
                    print("  ✅ Added DEGLARE env vars to worker-gpu-1")
        else:
            print("  ✅ docker-compose: worker-gpu-1 already has DEGLARE vars")
        
        if not self.dry_run and content != original:
            compose_path.write_text(content)

    # ================================================================
    # FIX 3: Ensure deglare.py is importable from tasks.py
    # ================================================================
    def _ensure_deglare_accessible(self):
        """Ensure deglare.py can be imported by tasks.py"""
        deglare_rtsp = self.root / "worker" / "alpr_worker" / "rtsp" / "deglare.py"
        
        if not deglare_rtsp.exists():
            self.warnings.append("deglare.py not found in rtsp/ — need to create it")
            return
        
        # Check that the import path works
        # tasks.py is in alpr_worker/tasks.py
        # deglare.py is in alpr_worker/rtsp/deglare.py
        # Import: from .rtsp.deglare import HeadlightDeglare ← should work
        
        # Verify deglare.py has HeadlightDeglare class
        content = deglare_rtsp.read_text()
        if "class HeadlightDeglare" not in content:
            self.warnings.append("deglare.py exists but doesn't have HeadlightDeglare class!")
            return
        
        if "def process_for_detection" not in content:
            self.warnings.append("deglare.py missing process_for_detection method!")
            return
        
        print("  ✅ deglare.py: HeadlightDeglare + process_for_detection available")
        self.changes.append("Verified deglare.py is importable from tasks.py")


def main():
    parser = argparse.ArgumentParser(description="Fix ALPR detection pipeline")
    parser.add_argument("--check", action="store_true", help="Check issues only")
    parser.add_argument("--apply", action="store_true", help="Apply fixes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change")
    parser.add_argument("--root", type=str, help="Project root directory")
    args = parser.parse_args()

    root = Path(args.root) if args.root else find_project_root()
    print(f"Project root: {root}")

    fixer = PipelineFixer(root, dry_run=args.dry_run)

    if args.check or (not args.apply and not args.dry_run):
        fixer.check()
    
    if args.apply or args.dry_run:
        if args.dry_run:
            print("\n[DRY RUN — no files will be modified]\n")
        fixer.apply()


if __name__ == "__main__":
    main()
