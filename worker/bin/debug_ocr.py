#!/usr/bin/env python3
import json
import sys
from dataclasses import asdict

from alpr_worker.inference.ocr import PlateOCR, debug_read


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: debug_ocr.py <crop_image_path>")
        return 2

    image_path = sys.argv[1]
    out = debug_read(image_path, output_prefix="/tmp/ocr_debug")
    if "error" in out:
        print(out["error"])
        return 1

    result = out["result"]
    if hasattr(result, "__dataclass_fields__"):
        print("result:", json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print("result:", result)

    print("intermediates:")
    for name, path in out["images"].items():
        print(f"  {name}: {path}")

    raw = out.get("raw", {})
    print("raw easyocr/candidates:", json.dumps(raw, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
