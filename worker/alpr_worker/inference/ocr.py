from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import cv2
import easyocr
import numpy as np
import torch

from .provinces import match_province, normalize_province
from .validate import is_valid_plate

log = logging.getLogger(__name__)

_THAI_DIGIT_MAP = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_THAI_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ0123456789"
_THAI_ONLY_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ"
_THAI_CONFUSION_MAP = {
    "ผ": ("ข", "พ"),
    "ข": ("ผ",),
    "พ": ("ผ",),
    "ฝ": ("ฟ", "ผ"),
    "ฟ": ("ฝ",),
    "บ": ("ป",),
    "ป": ("บ",),
    "ด": ("ต",),
    "ต": ("ด",),
    "ช": ("ซ", "ฃ"),
    "ซ": ("ช",),
    "ฃ": ("ช",),
    "ส": ("ศ", "ษ"),
    "ศ": ("ส", "ษ"),
    "ษ": ("ส", "ศ"),
}


@dataclass
class OCRResult:
    plate_text: str
    province: str
    confidence: float
    raw: Dict[str, Any]


class PlateOCR:
    def __init__(self) -> None:
        use_gpu = torch.cuda.is_available()
        self.reader = easyocr.Reader(["th", "en"], gpu=use_gpu, verbose=False)
        self.thai_reader = easyocr.Reader(["th"], gpu=use_gpu, verbose=False)

    def read(self, crop_path: str) -> OCRResult:
        return self.read_plate(crop_path)

    def read_plate(self, crop_path: str) -> OCRResult:
        img = cv2.imread(crop_path)
        if img is None:
            raise RuntimeError(f"Cannot read crop: {crop_path}")

        best: Dict[str, Any] = {
            "plate_text": "",
            "province": "",
            "confidence": 0.0,
            "score": -1.0,
            "variant": "",
            "lines": [],
            "candidates": [],
            "line_province_score": 0.0,
        }

        for variant_name, variant_img in self._build_variants(img):
            detections = self.reader.readtext(variant_img, detail=1, allowlist=_THAI_ALLOWLIST)
            candidate = self._evaluate_variant(variant_name, detections)
            if candidate["score"] > best["score"]:
                best = candidate

        roi_province = self._province_roi_pass(img)
        final_province = best["province"]
        if roi_province["province"]:
            roi_score = float(roi_province.get("score") or 0.0)
            line_score = float(best.get("line_province_score") or 0.0)
            if not final_province or roi_score >= max(70.0, line_score + 5.0):
                final_province = roi_province["province"]
                
        confidence = max(0.0, min(float(best["confidence"]), 1.0))
        if confidence < 0.6:
            log.warning(
                "Low OCR confidence variant=%s candidates=%s",
                best["variant"],
                best["candidates"][:3],
            )

        return OCRResult(
            plate_text=best["plate_text"],
            province=final_province,
            confidence=confidence,
            raw={
                "chosen_variant": best["variant"],
                "lines": best["lines"],
                "candidates": best["candidates"],
                "line_province": best["province"],
                "line_province_score": best["line_province_score"],
                "roi_province": roi_province,
            },
        )

    def _build_variants(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(gray)
        adaptive = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
        otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        up2 = cv2.resize(clahe, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        up2_adaptive = cv2.resize(adaptive, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)
        up2_otsu = cv2.resize(otsu, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)
        return [
            ("gray", gray),
            ("clahe", clahe),
            ("adaptive", adaptive),
            ("otsu", otsu),
            ("upscale_x2", up2),
            ("upscale_adaptive_x2", up2_adaptive),
            ("upscale_otsu_x2", up2_otsu),
        ]

    def _evaluate_variant(self, variant_name: str, detections: Sequence[Tuple[Any, str, float]]) -> Dict[str, Any]:
        lines, tokens = self._group_tokens_to_lines(detections)
        line_texts = ["".join(tok["text"] for tok in line) for line in lines]

        top_line = line_texts[0] if line_texts else ""
        plate_candidates = self._plate_candidates(top_line, tokens)
        best_plate = plate_candidates[0] if plate_candidates else {"text": "", "score": 0.0, "confidence": 0.0}

        bottom_line = line_texts[1] if len(line_texts) > 1 else ""
        province, province_score = match_province(bottom_line)
        if not province:
            merged = "".join(line_texts)
            province, province_score = match_province(merged, threshold=64)
        province = normalize_province(province or bottom_line, threshold=64)

        score = best_plate["score"] + (0.08 if province else 0.0)
        return {
            "variant": variant_name,
            "plate_text": best_plate["text"],
            "confidence": best_plate["confidence"],
            "score": score,
            "province": province,
            "line_province_score": province_score,
            "lines": line_texts,
            "candidates": plate_candidates,
            "tokens": tokens,
        }

    def _plate_candidates(self, top_line: str, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = self._normalize_plate(top_line)
        if not normalized:
            return []

        confs = [float(t["conf"]) for t in tokens] or [0.0]
        base_conf = float(np.mean(confs))
        valid_bonus = 0.25 if is_valid_plate(normalized) else 0.0

        candidates = [{
            "name": "top_line",
            "text": normalized,
            "confidence": max(0.0, min(base_conf + valid_bonus, 1.0)),
            "score": base_conf + valid_bonus,
        }]

        for alt_text, swaps in self._expand_confusion_candidates(normalized):
            penalty = 0.06 * swaps
            alt_bonus = 0.1 if is_valid_plate(alt_text) else 0.0
            candidates.append({
                "name": f"confusion_swap_{swaps}",
                "text": alt_text,
                "confidence": max(0.0, min(base_conf + valid_bonus + alt_bonus - penalty, 1.0)),
                "score": base_conf + valid_bonus + alt_bonus - penalty,
            })

        if re.match(r"^[ก-ฮ]{1,2}\d{4}$", normalized):
            prefixed = f"1{normalized}"
            candidates.append({
                "name": "prefixed_digit",
                "text": prefixed,
                "confidence": max(0.0, min(base_conf + 0.1, 1.0)),
                "score": base_conf + (0.22 if is_valid_plate(prefixed) else 0.02),
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _province_roi_pass(self, image: np.ndarray) -> Dict[str, Any]:
        h, w = image.shape[:2]
        start = int(h * 0.55)
        roi = image[start:h, 0:w]
        if roi.size == 0:
            return {"province": "", "score": 0.0, "variant": "", "texts": []}

        best = {"province": "", "score": 0.0, "variant": "", "texts": []}
        for name, variant in self._build_province_roi_variants(roi):
            detections = self.thai_reader.readtext(variant, detail=1, allowlist=_THAI_ONLY_ALLOWLIST)
            texts = [self._normalize_text(t) for _, t, c in detections if float(c or 0.0) >= 0.1]
            texts = [t for t in texts if t]
            if not texts:
                continue
            for text in ["".join(texts)] + texts:
                province, score = match_province(text, threshold=58)
                province = normalize_province(province or text, threshold=58)
                if province and score > best["score"]:
                    best = {"province": province, "score": float(score), "variant": name, "texts": texts}
        return best

    def _build_province_roi_variants(self, roi: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        up = cv2.resize(gray, None, fx=2.6, fy=2.6, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(up)
        sharpen = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))
        adaptive = cv2.adaptiveThreshold(sharpen, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
        return [("roi_upscale", up), ("roi_clahe_sharpen", sharpen), ("roi_adaptive", adaptive)]

    def _group_tokens_to_lines(self, detections: Sequence[Tuple[Any, str, float]]) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        tokens: List[Dict[str, Any]] = []
        for box, text, conf in detections:
            cleaned = self._normalize_text(text)
            if not cleaned:
                continue
            y = float(np.mean([pt[1] for pt in box]))
            x = float(np.mean([pt[0] for pt in box]))
            tokens.append({"text": cleaned, "conf": float(conf or 0.0), "x": x, "y": y})

        if not tokens:
            return [], []

        tokens.sort(key=lambda t: t["y"])
        ys = [t["y"] for t in tokens]
        threshold = max(8.0, (max(ys) - min(ys)) * 0.22)

        clusters: List[List[Dict[str, Any]]] = []
        for tok in tokens:
            if not clusters:
                clusters.append([tok])
                continue
            center = float(np.mean([x["y"] for x in clusters[-1]]))
            if abs(tok["y"] - center) <= threshold:
                clusters[-1].append(tok)
            else:
                clusters.append([tok])

        clusters = sorted(clusters, key=lambda c: np.mean([x["y"] for x in c]))[:2]
        for cluster in clusters:
            cluster.sort(key=lambda c: c["x"])
        return clusters, tokens

    def _normalize_text(self, text: str) -> str:
        norm = (text or "").translate(_THAI_DIGIT_MAP)
        norm = re.sub(r"[\s\-_.]", "", norm)
        norm = re.sub(r"[^0-9A-Za-zก-๙]", "", norm)
        return norm

    def _normalize_plate(self, text: str) -> str:
        norm = self._normalize_text(text)
        norm = re.sub(r"[^0-9ก-๙]", "", norm)
        return norm

    def _expand_confusion_candidates(self, text: str) -> Iterable[Tuple[str, int]]:
        match = re.match(r"^([ก-ฮ]{1,2})(\d+)$", text)
        if not match:
            return []

        prefix, digits = match.groups()
        options: List[List[str]] = []
        for ch in prefix:
            alts = [ch]
            alts.extend(_THAI_CONFUSION_MAP.get(ch, ()))
            options.append(alts)

        variants = []
        for choice in itertools.product(*options):
            swapped = sum(1 for orig, alt in zip(prefix, choice) if orig != alt)
            if swapped == 0:
                continue
            variants.append(("".join(choice) + digits, swapped))

        seen = set()
        unique: List[Tuple[str, int]] = []
        for variant, swaps in variants:
            if variant in seen:
                continue
            seen.add(variant)
            unique.append((variant, swaps))
        return unique[:6]
