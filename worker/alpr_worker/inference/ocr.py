# worker/alpr_worker/inference/ocr.py
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class OCRResult:
    plate_text: str          # เช่น "กก1234"
    province: str            # เช่น "กรุงเทพมหานคร"
    conf: float              # 0..1
    raw: Dict[str, Any]      # debug payload


THAI_PROVINCES = [
    "กรุงเทพมหานคร","กระบี่","กาญจนบุรี","กาฬสินธุ์","กำแพงเพชร","ขอนแก่น","จันทบุรี","ฉะเชิงเทรา","ชลบุรี","ชัยนาท",
    "ชัยภูมิ","ชุมพร","เชียงราย","เชียงใหม่","ตรัง","ตราด","ตาก","นครนายก","นครปฐม","นครพนม","นครราชสีมา","นครศรีธรรมราช",
    "นครสวรรค์","นนทบุรี","นราธิวาส","น่าน","บึงกาฬ","บุรีรัมย์","ปทุมธานี","ประจวบคีรีขันธ์","ปราจีนบุรี","ปัตตานี","พระนครศรีอยุธยา",
    "พะเยา","พังงา","พัทลุง","พิจิตร","พิษณุโลก","เพชรบุรี","เพชรบูรณ์","แพร่","ภูเก็ต","มหาสารคาม","มุกดาหาร","แม่ฮ่องสอน",
    "ยะลา","ยโสธร","ร้อยเอ็ด","ระนอง","ระยอง","ราชบุรี","ลพบุรี","ลำปาง","ลำพูน","เลย","ศรีสะเกษ","สกลนคร","สงขลา","สตูล",
    "สมุทรปราการ","สมุทรสงคราม","สมุทรสาคร","สระแก้ว","สระบุรี","สิงห์บุรี","สุโขทัย","สุพรรณบุรี","สุราษฎร์ธานี","สุรินทร์",
    "หนองคาย","หนองบัวลำภู","อ่างทอง","อำนาจเจริญ","อุดรธานี","อุตรดิตถ์","อุทัยธานี","อุบลราชธานี"
]

def _normalize_plate_text(s: str) -> str:
    s = s.strip()
    s = s.replace(" ", "").replace("-", "")
    # keep thai letters + digits only
    s = re.sub(r"[^0-9ก-๙]", "", s)
    return s

def _best_province_guess(text: str) -> str:
    # very simple: pick exact match if found
    for p in THAI_PROVINCES:
        if p in text:
            return p
    return ""

class PlateOCR:
    """
    Production-safe OCR wrapper with a stable API: read(crop_path) -> OCRResult

    You can choose backend by OCR_BACKEND env:
      - OCR_BACKEND=tesseract  (requires tesseract-ocr + tha traineddata)
      - OCR_BACKEND=none (default) - returns empty but does not crash
    """
    def __init__(self):
        self.backend = os.getenv("OCR_BACKEND", "none").lower()

        if self.backend == "tesseract":
            try:
                import pytesseract  # type: ignore
                self.pytesseract = pytesseract
                self.lang = os.getenv("TESS_LANG", "tha+eng")
            except Exception as e:
                log.warning("Tesseract backend requested but not available: %s. Falling back to none.", e)
                self.backend = "none"

    def read(self, crop_path: str) -> OCRResult:
        if self.backend == "tesseract":
            return self._read_tesseract(crop_path)

        # default safe fallback
        return OCRResult(
            plate_text="",
            province="",
            conf=0.0,
            raw={"backend": self.backend, "note": "OCR backend not configured"},
        )

    def _read_tesseract(self, crop_path: str) -> OCRResult:
        img = cv2.imread(crop_path)
        if img is None:
            raise RuntimeError(f"Cannot read crop: {crop_path}")

        # preprocess: grayscale + threshold
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 7, 50, 50)
        thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                    cv2.THRESH_BINARY, 31, 10)

        config = os.getenv("TESS_CONFIG", "--psm 7")
        txt = self.pytesseract.image_to_string(thr, lang=self.lang, config=config)

        plate = _normalize_plate_text(txt)
        prov = _best_province_guess(txt)

        # heuristic confidence
        conf = 0.6 if len(plate) >= 4 else 0.3
        return OCRResult(
            plate_text=plate,
            province=prov,
            conf=float(conf),
            raw={"backend": "tesseract", "raw_text": txt},
        )
