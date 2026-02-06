#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from alpr_worker.inference.ocr import PlateOCR


def default_samples(repo_root: Path) -> list[Path]:
    crops = repo_root / "storage" / "crops"
    return sorted(crops.glob("*.jpg"))[:5]


def main() -> None:
    parser = argparse.ArgumentParser(description="Small OCR smoke test for Thai ALPR PlateOCR")
    parser.add_argument("images", nargs="*", help="Optional list of crop image paths")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    if args.images:
        samples = [Path(p) for p in args.images]
    else:
        samples = default_samples(repo_root)

    if not samples:
        print("No sample images found.")
        return

    ocr = PlateOCR()
    for img in samples:
        res = ocr.read_plate(str(img))
        print(f"{img}: plate={res.plate_text} province={res.province} conf={res.confidence:.3f}")


if __name__ == "__main__":
    main()
