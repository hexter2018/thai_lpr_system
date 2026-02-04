# active_learning.py
from __future__ import annotations

import os
import json
import shutil
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ScanLog, ScanStatus


def _safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


async def export_mlpr_hard_examples(
    session: AsyncSession,
    storage_base: str = "./storage",
    export_base: str = "./exports",
) -> Dict[str, Any]:
    """
    Query MLPR logs, copy cropped images + create label files.
    Output folder: exports/dataset_for_retraining_YYYYMMDD/images + labels
    Label format here is OCR-supervision-friendly:
      <license_text>\t<province>
    Also stores a JSON sidecar for traceability.
    """
    date_str = datetime.utcnow().strftime("%Y%m%d")
    root = os.path.join(export_base, f"dataset_for_retraining_{date_str}")
    img_dir = os.path.join(root, "images")
    lbl_dir = os.path.join(root, "labels")
    meta_dir = os.path.join(root, "meta")

    _safe_mkdir(img_dir)
    _safe_mkdir(lbl_dir)
    _safe_mkdir(meta_dir)

    q = select(ScanLog).where(ScanLog.status == ScanStatus.MLPR).order_by(ScanLog.created_at.asc())
    rows = (await session.execute(q)).scalars().all()

    exported = 0
    skipped = 0

    for log in rows:
        vr = log.verification_result or {}
        corrected_license = (vr.get("corrected_license") or "").strip()
        corrected_province = (vr.get("corrected_province") or "").strip()

        if not corrected_license or not corrected_province:
            skipped += 1
            continue

        # Paths stored like "storage/2026-02-04/crop_xxx.jpg"
        # Convert to absolute: storage_base + relative inside "storage/"
        rel = log.cropped_plate_image_path.replace("\\", "/")
        if rel.startswith("storage/"):
            rel_inside = rel[len("storage/"):]
        else:
            rel_inside = rel

        src_img = os.path.join(storage_base, rel_inside)
        if not os.path.exists(src_img):
            skipped += 1
            continue

        # Destination filenames
        base_name = f"log_{log.id}"
        dst_img = os.path.join(img_dir, f"{base_name}.jpg")
        dst_lbl = os.path.join(lbl_dir, f"{base_name}.txt")
        dst_meta = os.path.join(meta_dir, f"{base_name}.json")

        shutil.copy2(src_img, dst_img)

        # OCR label format (simple & effective for retraining OCR)
        with open(dst_lbl, "w", encoding="utf-8") as f:
            f.write(f"{corrected_license}\t{corrected_province}\n")

        # Metadata for traceability
        meta = {
            "log_id": log.id,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "detected_text": log.detected_text,
            "detected_province": log.detected_province,
            "confidence_score": log.confidence_score,
            "corrected_license": corrected_license,
            "corrected_province": corrected_province,
            "source_cropped_path": log.cropped_plate_image_path,
        }
        with open(dst_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        exported += 1

    return {
        "dataset_folder": root,
        "exported": exported,
        "skipped": skipped,
        "total_mlpr": len(rows),
    }
