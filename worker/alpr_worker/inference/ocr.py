from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .provinces import best_province_from_text, normalize_province

log = logging.getLogger(__name__)


@dataclass
class OCRResult:
    plate_text: str
    province: str
    conf: float
    raw: Dict[str, Any]


_THAI_TO_ARABIC = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_CHAR_FIX_MAP = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})


def normalize_plate_text(text: str) -> str:
    value = (text or "").strip().translate(_THAI_TO_ARABIC)
    value = re.sub(r"[\s\-_.]", "", value)
    value = re.sub(r"[^0-9A-Za-zก-๙]", "", value)
    chars: List[str] = []
    for ch in value:
        if re.match(r"[ก-๙0-9]", ch):
            chars.append(ch)
        else:
            chars.append(ch.translate(_CHAR_FIX_MAP))
    value = "".join(chars)
    return re.sub(r"[^0-9ก-๙]", "", value)


def plate_structure_score(text: str) -> float:
    candidate = normalize_plate_text(text)
    if not candidate:
        return 0.0

    thai_count = len(re.findall(r"[ก-๙]", candidate))
    digit_count = len(re.findall(r"[0-9]", candidate))
    length = len(candidate)

    score = 0.0
    if 3 <= length <= 8:
        score += 0.25
    if 1 <= thai_count <= 3:
        score += 0.3
    if 1 <= digit_count <= 4:
        score += 0.3
    if re.match(r"^[ก-๙]{1,3}[0-9]{1,4}$", candidate):
        score += 0.2
    return min(1.0, score)


class PlateOCR:
    """OCR wrapper with EasyOCR-first pipeline and robust province extraction."""

    def __init__(self):
        self.backend = os.getenv("OCR_BACKEND", "easyocr").lower()
        self.easyocr_reader = None
        self.easyocr_thai_reader = None

        if self.backend == "easyocr":
            try:
                import easyocr  # type: ignore

                self.easyocr_reader = easyocr.Reader(["th", "en"], gpu=False, verbose=False)
                self.easyocr_thai_reader = easyocr.Reader(["th"], gpu=False, verbose=False)
            except Exception as exc:
                log.warning("EasyOCR unavailable: %s", exc)
                self.backend = "none"

    def read(self, crop_path: str) -> OCRResult:
        return self.read_plate(crop_path)

    def read_plate(self, crop_path: str) -> OCRResult:
        if self.backend == "easyocr":
            return self._read_easyocr(crop_path)

        return OCRResult(plate_text="", province="", conf=0.0, raw={"backend": self.backend, "note": "OCR backend unavailable"})

    def _ocr_easyocr(
        self,
        image: np.ndarray,
        reader,
        allowlist: Optional[str] = None,
        detail: int = 1,
    ) -> Sequence[Any]:
        kwargs = {
            "detail": detail,
            "paragraph": False,
            "decoder": "greedy",
            "contrast_ths": 0.05,
            "adjust_contrast": 0.9,
            "text_threshold": 0.5,
            "low_text": 0.3,
            "link_threshold": 0.3,
        }
        if allowlist:
            kwargs["allowlist"] = allowlist
        return reader.readtext(image, **kwargs)

    def _preprocess_plate_variants(self, bgr: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(up)
        sharpen = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))
        bilateral = cv2.bilateralFilter(sharpen, 5, 70, 70)

        otsu = cv2.threshold(bilateral, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        adaptive = cv2.adaptiveThreshold(bilateral, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 5)
        inv = cv2.bitwise_not(otsu)

        return [
            ("gray_up", up),
            ("clahe_sharp", sharpen),
            ("otsu", otsu),
            ("adaptive", adaptive),
            ("otsu_inv", inv),
        ]

    def _province_roi_variants(self, bgr: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        h = bgr.shape[0]
        y0 = int(h * 0.55)
        roi = bgr[y0:, :]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        up = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(up)
        sharp = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 6, -1], [0, -1, 0]], dtype=np.float32))
        adaptive = cv2.adaptiveThreshold(sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 7)
        otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        return [
            ("province_up", up),
            ("province_clahe_sharp", sharp),
            ("province_adaptive", adaptive),
            ("province_otsu", otsu),
        ]

    def _extract_best_plate(self, lines: Sequence[Tuple[str, float]]) -> Tuple[str, float]:
        best_plate = ""
        best_score = 0.0
        for text, text_conf in lines:
            tokens = re.findall(r"[0-9A-Za-zก-๙]{3,10}", text or "")
            if not tokens:
                tokens = [text]
            for token in tokens:
                normalized = normalize_plate_text(token)
                structure = plate_structure_score(normalized)
                score = (0.7 * structure) + (0.3 * text_conf)
                if score > best_score:
                    best_plate = normalized
                    best_score = score
        return best_plate, best_score

    def _best_province_from_lines(self, lines: Sequence[Tuple[str, float]]) -> Tuple[str, float]:
        best_name = ""
        best_score = 0.0
        for text, line_conf in lines:
            province, prov_conf = best_province_from_text(text)
            score = (0.6 * prov_conf) + (0.4 * line_conf)
            if province and score > best_score:
                best_name = province
                best_score = score
        return normalize_province(best_name), best_score

    def _read_easyocr(self, crop_path: str) -> OCRResult:
        bgr = cv2.imread(crop_path)
        if bgr is None:
            raise RuntimeError(f"Cannot read crop: {crop_path}")

        plate_variants = self._preprocess_plate_variants(bgr)
        plate_lines: List[Tuple[str, float]] = []
        raw_plate_reads: List[Dict[str, Any]] = []
        for name, variant in plate_variants:
            lines = self._ocr_easyocr(variant, self.easyocr_reader, detail=1)
            for item in lines:
                _, text, conf = item
                conf_f = float(conf or 0.0)
                plate_lines.append((str(text), conf_f))
                raw_plate_reads.append({"variant": name, "text": text, "conf": conf_f})

        best_plate, plate_score = self._extract_best_plate(plate_lines)
        line_province, line_province_score = self._best_province_from_lines(plate_lines)

        roi_variants = self._province_roi_variants(bgr)
        thai_allowlist = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮ"
        roi_best_province = ""
        roi_best_score = 0.0
        roi_raw: List[Dict[str, Any]] = []

        for name, variant in roi_variants:
            lines = self._ocr_easyocr(variant, self.easyocr_thai_reader, allowlist=thai_allowlist, detail=1)
            for item in lines:
                _, text, conf = item
                conf_f = float(conf or 0.0)
                province, prov_conf = best_province_from_text(str(text))
                score = (0.7 * prov_conf) + (0.3 * conf_f)
                roi_raw.append({"variant": name, "text": text, "conf": conf_f, "province": province, "score": score})
                if province and score > roi_best_score:
                    roi_best_province = province
                    roi_best_score = score

        province = roi_best_province if roi_best_province else line_province
        province_score = roi_best_score if roi_best_province else line_province_score

        total_conf = min(1.0, (0.72 * plate_score) + (0.28 * province_score))
        if province:
            total_conf = min(1.0, total_conf + 0.05)

        return OCRResult(
            plate_text=best_plate,
            province=normalize_province(province),
            conf=float(total_conf),
            raw={
                "backend": "easyocr",
                "plate_reads": raw_plate_reads[:30],
                "province_roi_reads": roi_raw[:40],
                "selected": {
                    "plate": best_plate,
                    "province": province,
                    "plate_score": plate_score,
                    "line_province_score": line_province_score,
                    "roi_province_score": roi_best_score,
                    "province_source": "roi" if roi_best_province else "line",
                },
            },
        )
