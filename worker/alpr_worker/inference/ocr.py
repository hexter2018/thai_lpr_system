from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import get_close_matches, SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import easyocr
import numpy as np
import torch

from .provinces import THAI_PROVINCES

log = logging.getLogger(__name__)

_THAI_DIGIT_MAP = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_PLATE_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮ0123456789"
_PROVINCE_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ"
_PLATE_PATTERN = re.compile(r"^\d{0,2}[ก-ฮ]{1,2}\d{1,4}$")

try:
    from rapidfuzz import process as rapid_process  # type: ignore
except Exception:  # pragma: no cover
    rapid_process = None


@dataclass
class OCRResult:
    plate_text: str
    province: str
    conf: float
    raw: Dict[str, Any]

    @property
    def confidence(self) -> float:
        return self.conf


class PlateOCR:
    _reader: easyocr.Reader | None = None
    _thai_reader: easyocr.Reader | None = None

    def __init__(self) -> None:
        self.reader = self._get_reader(thai_only=False)
        self.thai_reader = self._get_reader(thai_only=True)

    @classmethod
    def _get_reader(cls, thai_only: bool = False) -> easyocr.Reader:
        if thai_only and cls._thai_reader is not None:
            return cls._thai_reader
        if not thai_only and cls._reader is not None:
            return cls._reader

        langs = ["th"] if thai_only else ["th", "en"]
        reader: easyocr.Reader | None = None
        if torch.cuda.is_available():
            try:
                reader = easyocr.Reader(langs, gpu=True, verbose=False)
            except Exception as exc:  # pragma: no cover
                log.warning("easyocr gpu init failed, falling back to cpu: %s", exc)
        if reader is None:
            reader = easyocr.Reader(langs, gpu=False, verbose=False)

        if thai_only:
            cls._thai_reader = reader
        else:
            cls._reader = reader
        return reader

    def read(self, image_path: str) -> OCRResult:
        try:
            image = cv2.imread(image_path)
            if image is None:
                return OCRResult("", "", 0.0, {"error": f"cannot_read:{image_path}"})
            plate = self._read_plate_text(image)
            province = self._read_province(image)
            final_conf = self._score_result(plate["text"], plate["conf"])
            if province["province"]:
                final_conf = min(1.0, final_conf + 0.04)
            return OCRResult(
                plate_text=plate["text"],
                province=province["province"],
                conf=max(0.0, min(1.0, final_conf)),
                raw={"plate": plate, "province": province},
            )
        except Exception as exc:  # pragma: no cover
            log.exception("PlateOCR.read failed: %s", exc)
            return OCRResult("", "", 0.0, {"error": str(exc)})

    def _read_plate_text(self, image: np.ndarray) -> Dict[str, Any]:
        variants = self._build_plate_variants(image)
        all_candidates: List[Dict[str, Any]] = []
        for name, variant in variants:
            detections = self.reader.readtext(variant, detail=1, allowlist=_PLATE_ALLOWLIST)
            all_candidates.append(self._candidate_from_detections(name, detections))

        best = max(all_candidates, key=lambda c: c["score"], default={"text": "", "conf": 0.0, "score": 0.0})
        left = self._detect_left_digit(image)

        merged = best["text"]
        forced = False
        if left and merged and not re.match(r"^\d", merged):
            merged = f"{left}{merged}"
            forced = True
        elif left and not merged:
            merged = left
            forced = True

        merged = self._normalize_plate(merged)
        merged = self._coerce_plate_pattern(merged)
        if left and merged and not merged.startswith(left):
            if re.search(r"[ก-ฮ]", merged):
                merged = f"{left}{merged}"
                forced = True

        conf = best.get("conf", 0.0)
        if forced:
            conf = min(1.0, conf + 0.05)

        return {
            "text": merged,
            "conf": conf,
            "best_variant": best.get("variant", ""),
            "left_digit": left,
            "forced_prepend": forced,
            "candidates": all_candidates,
        }

    def _build_plate_variants(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
        denoise = cv2.fastNlMeansDenoising(clahe, None, h=10, templateWindowSize=7, searchWindowSize=21)
        adaptive = cv2.adaptiveThreshold(denoise, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5)
        adaptive_inv = cv2.adaptiveThreshold(denoise, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5)

        kernel = np.ones((2, 2), np.uint8)
        close_img = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel, iterations=1)
        open_img = cv2.morphologyEx(close_img, cv2.MORPH_OPEN, kernel, iterations=1)
        close_inv = cv2.morphologyEx(adaptive_inv, cv2.MORPH_CLOSE, kernel, iterations=1)

        return [
            ("gray", self._pad(gray)),
            ("clahe", self._pad(clahe)),
            ("adaptive", self._pad(adaptive)),
            ("adaptive_inv", self._pad(adaptive_inv)),
            ("morph", self._pad(open_img)),
            ("morph_inv", self._pad(close_inv)),
        ]

    def _detect_left_digit(self, image: np.ndarray) -> str:
        h, w = image.shape[:2]
        left_w = max(1, int(w * 0.38))
        roi = image[:, :left_w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.4, tileGridSize=(8, 8)).apply(gray)
        thr = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 3)
        thr_inv = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 3)
        k = np.ones((2, 2), np.uint8)
        variants = [thr, thr_inv, cv2.morphologyEx(thr, cv2.MORPH_CLOSE, k, iterations=1)]

        best_digit = ""
        best_conf = 0.0
        for variant in variants:
            detections = self.reader.readtext(self._pad(variant, border=14), detail=1, allowlist="0123456789")
            for _, text, conf in detections:
                digit = re.sub(r"\D", "", self._normalize_plate(text or ""))
                if digit and len(digit) <= 2 and float(conf or 0.0) >= best_conf:
                    best_digit = digit[0]
                    best_conf = float(conf or 0.0)
        return best_digit

    def _candidate_from_detections(self, variant: str, detections: Sequence[Tuple[Any, str, float]]) -> Dict[str, Any]:
        parts: List[Tuple[str, float]] = []
        for _, text, conf in detections:
            cleaned = self._normalize_plate(text or "")
            if not cleaned:
                continue
            parts.append((cleaned, max(0.0, float(conf or 0.0))))

        joined = self._coerce_plate_pattern("".join(p[0] for p in parts))
        if not joined and parts:
            joined = self._coerce_plate_pattern(max((p[0] for p in parts), key=len))

        conf = self._length_weighted_conf(parts)
        score = conf
        if _PLATE_PATTERN.match(joined):
            score += 0.2
        if not re.search(r"\d{1,4}$", joined or ""):
            score -= 0.2
        if len(joined) < 4:
            score -= 0.15

        return {
            "variant": variant,
            "text": joined,
            "conf": max(0.0, min(1.0, conf)),
            "score": score,
            "parts": parts,
        }

    def _score_result(self, text: str, base_conf: float) -> float:
        conf = float(base_conf)
        if not text:
            return 0.0
        if not re.search(r"\d{1,4}$", text):
            conf -= 0.22
        if not re.search(r"[ก-ฮ]{1,2}", text):
            conf -= 0.25
        if len(text) < 5:
            conf -= 0.15
        if _PLATE_PATTERN.match(text):
            conf += 0.12
        return max(0.0, min(1.0, conf))

    def _read_province(self, image: np.ndarray) -> Dict[str, Any]:
        h, w = image.shape[:2]
        roi = image[int(h * 0.70):h, 0:w]
        if roi.size == 0:
            return {"province": "", "confidence": 0.0, "raw_text": ""}

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
        denoise = cv2.bilateralFilter(clahe, 7, 45, 45)
        adaptive = cv2.adaptiveThreshold(denoise, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 3)
        variants = [self._pad(gray), self._pad(clahe), self._pad(adaptive)]

        texts: List[Tuple[str, float]] = []
        for variant in variants:
            for _, text, conf in self.thai_reader.readtext(variant, detail=1, allowlist=_PROVINCE_ALLOWLIST):
                cleaned = self._normalize_province(text or "")
                if cleaned:
                    texts.append((cleaned, float(conf or 0.0)))

        joined = self._normalize_province("".join(t[0] for t in texts))
        best_text = joined if joined else (texts[0][0] if texts else "")
        province, score = self._match_province(best_text)
        return {
            "province": province,
            "confidence": score,
            "raw_text": best_text,
            "texts": texts,
        }

    def _match_province(self, text: str) -> Tuple[str, float]:
        if not text:
            return "", 0.0
        if text in THAI_PROVINCES:
            return text, 1.0
        if rapid_process is not None:
            result = rapid_process.extractOne(text, THAI_PROVINCES)
            if result:
                return result[0], float(result[1]) / 100.0

        close = get_close_matches(text, THAI_PROVINCES, n=1, cutoff=0.45)
        if close:
            ratio = SequenceMatcher(None, text, close[0]).ratio()
            return close[0], float(ratio)
        return "", 0.0

    def _coerce_plate_pattern(self, text: str) -> str:
        text = self._normalize_plate(text)
        if not text:
            return ""

        if _PLATE_PATTERN.match(text):
            return text

        thai_match = re.search(r"[ก-ฮ]{1,2}", text)
        if not thai_match:
            return text

        thai = thai_match.group(0)
        left = re.sub(r"\D", "", text[:thai_match.start()])[:2]
        right = re.sub(r"\D", "", text[thai_match.end():])[:4]
        merged = f"{left}{thai}{right}"
        return merged if merged else text

    def _length_weighted_conf(self, parts: Sequence[Tuple[str, float]]) -> float:
        if not parts:
            return 0.0
        total_len = sum(len(p[0]) for p in parts)
        if total_len <= 0:
            return 0.0
        return sum(len(p[0]) * float(p[1]) for p in parts) / float(total_len)

    def _normalize_plate(self, text: str) -> str:
        norm = (text or "").strip().translate(_THAI_DIGIT_MAP)
        norm = re.sub(r"[\s\-_.]", "", norm)
        norm = re.sub(r"[^0-9A-Za-zก-๙]", "", norm)
        norm = re.sub(r"([0-9])O(?=[0-9])", r"\g<1>0", norm)
        norm = re.sub(r"(?<=[0-9])O([0-9])", r"0\g<1>", norm)
        norm = re.sub(r"(?<=[0-9])I(?=[0-9])", "1", norm)
        norm = re.sub(r"(?<=[0-9])S(?=[0-9])", "5", norm)
        return norm

    def _normalize_province(self, text: str) -> str:
        norm = (text or "").strip().translate(_THAI_DIGIT_MAP)
        norm = re.sub(r"[\s\-_.]", "", norm)
        norm = norm.replace("ฯ", "")
        norm = re.sub(r"[^ก-๙]", "", norm)
        return norm

    def _pad(self, image: np.ndarray, border: int = 12) -> np.ndarray:
        return cv2.copyMakeBorder(image, border, border, border, border, cv2.BORDER_CONSTANT, value=255)


def debug_read(image_path: str, output_prefix: str = "/tmp/ocr_debug") -> Dict[str, Any]:
    """Debug helper used by worker/bin/debug_ocr.py."""
    ocr = PlateOCR()
    image = cv2.imread(image_path)
    if image is None:
        return {"error": f"cannot_read:{image_path}"}

    outputs: Dict[str, Any] = {}
    for idx, (name, variant) in enumerate(ocr._build_plate_variants(image)):
        path = f"{output_prefix}_plate_{idx}_{name}.png"
        cv2.imwrite(path, variant)
        outputs[name] = path

    h, w = image.shape[:2]
    province_roi = image[int(h * 0.70):h, 0:w]
    cv2.imwrite(f"{output_prefix}_province_roi.png", province_roi)

    result = ocr.read(image_path)
    return {
        "images": outputs,
        "result": result,
        "raw": result.raw,
    }
