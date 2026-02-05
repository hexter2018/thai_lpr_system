from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Dict, Any, List

import cv2
from rapidfuzz import process, fuzz

log = logging.getLogger(__name__)


@dataclass
class OCRResult:
    plate_text: str
    province: str
    conf: float
    raw: Dict[str, Any]


THAI_PROVINCES = [
    "กรุงเทพมหานคร","กระบี่","กาญจนบุรี","กาฬสินธุ์","กำแพงเพชร","ขอนแก่น","จันทบุรี","ฉะเชิงเทรา","ชลบุรี","ชัยนาท",
    "ชัยภูมิ","ชุมพร","เชียงราย","เชียงใหม่","ตรัง","ตราด","ตาก","นครนายก","นครปฐม","นครพนม","นครราชสีมา","นครศรีธรรมราช",
    "นครสวรรค์","นนทบุรี","นราธิวาส","น่าน","บึงกาฬ","บุรีรัมย์","ปทุมธานี","ประจวบคีรีขันธ์","ปราจีนบุรี","ปัตตานี","พระนครศรีอยุธยา",
    "พะเยา","พังงา","พัทลุง","พิจิตร","พิษณุโลก","เพชรบุรี","เพชรบูรณ์","แพร่","ภูเก็ต","มหาสารคาม","มุกดาหาร","แม่ฮ่องสอน",
    "ยะลา","ยโสธร","ร้อยเอ็ด","ระนอง","ระยอง","ราชบุรี","ลพบุรี","ลำปาง","ลำพูน","เลย","ศรีสะเกษ","สกลนคร","สงขลา","สตูล",
    "สมุทรปราการ","สมุทรสงคราม","สมุทรสาคร","สระแก้ว","สระบุรี","สิงห์บุรี","สุโขทัย","สุพรรณบุรี","สุราษฎร์ธานี","สุรินทร์",
    "หนองคาย","หนองบัวลำภู","อ่างทอง","อำนาจเจริญ","อุดรธานี","อุตรดิตถ์","อุทัยธานี","อุบลราชธานี"
]

_THAI_ENG_MAP = str.maketrans({
    "O": "0", "o": "0",
    "I": "1", "l": "1", "|": "1",
    "Z": "2",
    "S": "5",
    "B": "8",
    "G": "6",
})


def _normalize_plate_text(s: str) -> str:
    s = (s or "").strip().replace(" ", "").replace("-", "")
    s = re.sub(r"[^0-9A-Za-zก-๙]", "", s)
    if not s:
        return ""

    chars: List[str] = []
    for ch in s:
        if ch.isdigit():
            chars.append(ch)
            continue
        if re.match(r"[ก-๙]", ch):
            chars.append(ch)
            continue
        chars.append(ch.translate(_THAI_ENG_MAP))

    normalized = "".join(chars)
    normalized = re.sub(r"[^0-9ก-๙]", "", normalized)
    return normalized


def _plate_candidate_score(cand: str) -> float:
    if not cand:
        return 0.0

    thai_letters = len(re.findall(r"[ก-๙]", cand))
    digits = len(re.findall(r"[0-9]", cand))
    total = len(cand)

    score = 0.0
    if 4 <= total <= 8:
        score += 0.35
    if 1 <= thai_letters <= 3:
        score += 0.30
    if 1 <= digits <= 4:
        score += 0.25
    if re.match(r"^[ก-๙]{1,3}[0-9]{1,4}$", cand):
        score += 0.20

    return min(score, 1.0)


def _best_province_guess(text: str) -> str:
    if not text:
        return ""

    cleaned = re.sub(r"\s+", "", text)
    if not cleaned:
        return ""

    for p in THAI_PROVINCES:
        if p in cleaned:
            return p

    match = process.extractOne(cleaned, THAI_PROVINCES, scorer=fuzz.WRatio)
    if match and match[1] >= 78:
        return str(match[0])
    return ""


class PlateOCR:
    """OCR wrapper: read(crop_path) -> OCRResult."""

    def __init__(self):
        self.backend = os.getenv("OCR_BACKEND", "tesseract").lower()

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

        return OCRResult(
            plate_text="",
            province="",
            conf=0.0,
            raw={"backend": self.backend, "note": "OCR backend not configured"},
        )

    def _build_variants(self, gray):
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        variants = []
        variants.append(("gray", gray))

        blur = cv2.bilateralFilter(gray, 7, 60, 60)
        variants.append(("bilateral", blur))

        thr_otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        variants.append(("otsu", thr_otsu))

        thr_inv = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        variants.append(("otsu_inv", thr_inv))

        ada = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 5)
        variants.append(("adaptive", ada))

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        morph = cv2.morphologyEx(thr_otsu, cv2.MORPH_OPEN, kernel)
        variants.append(("morph_open", morph))

        return variants

    def _ocr_with_conf(self, img, psm: int):
        config = os.getenv(
            "TESS_CONFIG",
            f"--oem 3 --psm {psm} -c preserve_interword_spaces=0"
        )
        text = self.pytesseract.image_to_string(img, lang=self.lang, config=config)
        data = self.pytesseract.image_to_data(
            img,
            lang=self.lang,
            config=config,
            output_type=self.pytesseract.Output.DICT,
        )

        vals = []
        for raw_conf in data.get("conf", []):
            try:
                c = float(raw_conf)
            except (TypeError, ValueError):
                continue
            if c >= 0:
                vals.append(c)
        mean_conf = (sum(vals) / len(vals)) / 100.0 if vals else 0.0
        return text, float(max(0.0, min(mean_conf, 1.0)))

    def _extract_plate_from_text(self, text: str) -> str:
        raw = re.sub(r"[\s\-_.]", "", text or "")
        candidates = re.findall(r"[0-9A-Za-zก-๙]{4,10}", raw)
        if not candidates:
            candidates = [raw]

        best = ""
        best_score = -1.0
        for c in candidates:
            n = _normalize_plate_text(c)
            score = _plate_candidate_score(n)
            if score > best_score:
                best = n
                best_score = score
        return best

    def _read_tesseract(self, crop_path: str) -> OCRResult:
        img = cv2.imread(crop_path)
        if img is None:
            raise RuntimeError(f"Cannot read crop: {crop_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variants = self._build_variants(gray)

        best = {
            "plate": "",
            "province": "",
            "conf": 0.0,
            "raw_text": "",
            "variant": "",
            "psm": 0,
        }

        for name, var_img in variants:
            for psm in (6, 7, 11):
                txt, tconf = self._ocr_with_conf(var_img, psm)
                plate = self._extract_plate_from_text(txt)
                province = _best_province_guess(txt)

                structural = _plate_candidate_score(plate)
                score = (0.65 * structural) + (0.35 * tconf)
                if province:
                    score += 0.05

                if score > best["conf"]:
                    best = {
                        "plate": plate,
                        "province": province,
                        "conf": float(min(score, 1.0)),
                        "raw_text": txt,
                        "variant": name,
                        "psm": psm,
                    }

        return OCRResult(
            plate_text=best["plate"],
            province=best["province"],
            conf=float(best["conf"]),
            raw={
                "backend": "tesseract",
                "raw_text": best["raw_text"],
                "variant": best["variant"],
                "psm": best["psm"],
            },
        )
