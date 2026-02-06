from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import easyocr
import numpy as np
import torch

from .provinces import match_province, normalize_province
from .validate import is_valid_plate

log = logging.getLogger(__name__)

_THAI_DIGIT_MAP = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_PLATE_KEEP_RE = re.compile(r"[^0-9ก-๙]")
_PROVINCE_KEEP_RE = re.compile(r"[^A-Za-z0-9ก-๙]")

_THAI_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮ0123456789"


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
        image = cv2.imread(crop_path)
        if image is None:
            raise RuntimeError(f"Cannot read crop: {crop_path}")

        best: Dict[str, Any] = {"score": -1.0, "confidence": 0.0, "plate_text": "", "lines": [], "variant": "", "candidates": []}
        for variant_name, variant in self._build_plate_variants(image):
            detections = self.reader.readtext(variant, detail=1)
            candidate = self._evaluate_variant(variant_name, detections)
            if candidate["score"] > best["score"]:
                best = candidate

        line_province, line_score = self._province_from_lines(best.get("lines", []))
        roi_province = self._province_from_bottom_roi(image)

        final_province = line_province
        if roi_province["province"]:
            final_province = roi_province["province"]

        confidence = float(np.clip(best.get("confidence", 0.0), 0.0, 1.0))
        return OCRResult(
            plate_text=best.get("plate_text", ""),
            province=final_province,
            confidence=confidence,
            raw={
                "chosen_variant": best.get("variant", ""),
                "lines": best.get("lines", []),
                "line_province": line_province,
                "line_province_score": line_score,
                "roi_province": roi_province,
                "candidates": best.get("candidates", []),
            },
        )

    def _build_plate_variants(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
        adaptive = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
        otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        upscale_gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        upscale_clahe = cv2.resize(clahe, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        upscale_adaptive = cv2.resize(adaptive, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)

        return [
            ("gray", gray),
            ("clahe", clahe),
            ("adaptive", adaptive),
            ("otsu", otsu),
            ("upscale_gray_x2", upscale_gray),
            ("upscale_clahe_x2", upscale_clahe),
            ("upscale_adaptive_x2", upscale_adaptive),
        ]

    def _evaluate_variant(self, variant_name: str, detections: Sequence[Tuple[Any, str, float]]) -> Dict[str, Any]:
        lines, all_rows = self._group_tokens_to_lines(detections)
        line_texts = ["".join(tok["text"] for tok in line) for line in lines]
        top_line = line_texts[0] if line_texts else ""

        candidates: List[Dict[str, Any]] = []
        top_score = 0.0
        best_plate = ""

        for src in [top_line] + line_texts:
            norm_plate = self._normalize_plate_text(src)
            if not norm_plate:
                continue
            conf = self._mean_conf_for_text(all_rows, src)
            bonus = 0.35 if is_valid_plate(norm_plate) else 0.0
            score = conf + bonus
            candidates.append({"source": src, "normalized": norm_plate, "score": score, "valid": is_valid_plate(norm_plate)})
            if score > top_score:
                top_score = score
                best_plate = norm_plate

        if not candidates and all_rows:
            merged = "".join(r["text"] for r in sorted(all_rows, key=lambda r: r["x"]))
            norm_plate = self._normalize_plate_text(merged)
            if norm_plate:
                top_score = 0.25
                best_plate = norm_plate
                candidates.append({"source": merged, "normalized": norm_plate, "score": top_score, "valid": is_valid_plate(norm_plate)})

        confidence = float(np.clip(top_score, 0.0, 1.0))
        return {
            "variant": variant_name,
            "plate_text": best_plate,
            "confidence": confidence,
            "score": top_score,
            "lines": line_texts,
            "candidates": sorted(candidates, key=lambda c: c["score"], reverse=True)[:5],
        }

    def _province_from_lines(self, line_texts: List[str]) -> Tuple[str, float]:
        if len(line_texts) < 2:
            return "", 0.0
        bottom = self._normalize_province_text(line_texts[1])
        merged = self._normalize_province_text("".join(line_texts))

        p1, s1 = match_province(bottom, threshold=70)
        p2, s2 = match_province(merged, threshold=70)
        if s2 > s1:
            return p2, s2
        return p1, s1

    def _province_from_bottom_roi(self, image: np.ndarray) -> Dict[str, Any]:
        h, w = image.shape[:2]
        start_y = int(h * 0.55)
        roi = image[start_y:h, 0:w]
        if roi.size == 0:
            return {"province": "", "score": 0.0, "variant": "", "tokens": []}

        best = {"province": "", "score": 0.0, "variant": "", "tokens": []}
        for variant_name, variant in self._build_province_variants(roi):
            detections = self.thai_reader.readtext(variant, detail=1, allowlist=_THAI_ALLOWLIST)
            tokens = [self._normalize_province_text(text) for _, text, conf in detections if conf and float(conf) >= 0.10]
            tokens = [t for t in tokens if t]
            if not tokens:
                continue

            choices = ["".join(tokens)] + tokens
            for choice in choices:
                province, score = match_province(choice, threshold=64)
                if province and score > best["score"]:
                    best = {"province": normalize_province(province, threshold=60), "score": float(score), "variant": variant_name, "tokens": tokens}

        return best

    def _build_province_variants(self, roi: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        upscaled = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(upscaled)
        sharpen = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))
        adaptive = cv2.adaptiveThreshold(sharpen, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)
        return [("upscaled", upscaled), ("clahe_sharpen", sharpen), ("adaptive", adaptive)]

    def _group_tokens_to_lines(self, detections: Sequence[Tuple[Any, str, float]]) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        rows: List[Dict[str, Any]] = []
        for box, text, conf in detections:
            cleaned = self._normalize_province_text(text)
            if not cleaned:
                continue
            y_center = float(np.mean([pt[1] for pt in box]))
            x_center = float(np.mean([pt[0] for pt in box]))
            rows.append({"text": cleaned, "conf": float(conf or 0.0), "x": x_center, "y": y_center})

        if not rows:
            return [], []

        rows.sort(key=lambda r: r["y"])
        spread = max(r["y"] for r in rows) - min(r["y"] for r in rows)
        threshold = max(8.0, spread * 0.22)

        clusters: List[List[Dict[str, Any]]] = []
        for row in rows:
            if not clusters:
                clusters.append([row])
                continue
            mean_y = float(np.mean([x["y"] for x in clusters[-1]]))
            if abs(row["y"] - mean_y) <= threshold:
                clusters[-1].append(row)
            else:
                clusters.append([row])

        clusters = sorted(clusters, key=lambda c: np.mean([x["y"] for x in c]))[:2]
        for cluster in clusters:
            cluster.sort(key=lambda r: r["x"])
        return clusters, rows

    def _mean_conf_for_text(self, rows: List[Dict[str, Any]], source_text: str) -> float:
        if not rows:
            return 0.0
        present = [r["conf"] for r in rows if r["text"] and r["text"] in source_text]
        if not present:
            present = [r["conf"] for r in rows]
        return float(np.mean(present)) if present else 0.0

    def _normalize_plate_text(self, text: str) -> str:
        normalized = (text or "").translate(_THAI_DIGIT_MAP)
        normalized = re.sub(r"[\s\-_.]", "", normalized)
        normalized = _PLATE_KEEP_RE.sub("", normalized)
        return normalized

    def _normalize_province_text(self, text: str) -> str:
        normalized = (text or "").translate(_THAI_DIGIT_MAP)
        normalized = _PROVINCE_KEEP_RE.sub("", normalized)
        return normalized
