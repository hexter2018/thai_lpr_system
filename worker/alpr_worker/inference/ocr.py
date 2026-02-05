from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import easyocr
import numpy as np
import torch

from .provinces import normalize_province
from .validate import is_valid_plate

log = logging.getLogger(__name__)

_THAI_DIGIT_MAP = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


@dataclass
class OCRResult:
    plate_text: str
    province: str
    confidence: float
    raw: Dict[str, Any]


class PlateOCR:
    """EasyOCR pipeline for Thai plate + province extraction."""

    def __init__(self) -> None:
        self.reader = easyocr.Reader(["th", "en"], gpu=torch.cuda.is_available(), verbose=False)

    def read(self, crop_path: str) -> OCRResult:
        # Backward compatibility for existing callers.
        return self.read_plate(crop_path)

    def read_plate(self, crop_path: str) -> OCRResult:
        img = cv2.imread(crop_path)
        if img is None:
            raise RuntimeError(f"Cannot read crop: {crop_path}")

        variants = self._build_variants(img)
        best: Dict[str, Any] = {
            "plate_text": "",
            "province": "",
            "score": 0.0,
            "variant": "",
            "lines": [],
            "candidates": [],
        }

        for variant_name, variant_img in variants:
            detections = self.reader.readtext(variant_img, detail=1)
            candidate = self._evaluate_variant(variant_name, detections)
            if candidate["score"] > best["score"]:
                best = candidate

        confidence = max(0.0, min(float(best["score"]), 1.0))
        return OCRResult(
            plate_text=best["plate_text"],
            province=best["province"],
            confidence=confidence,
            raw={
                "chosen_variant": best["variant"],
                "lines": best["lines"],
                "candidates": best["candidates"],
            },
        )

    def _build_variants(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
        otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )

        variants: List[Tuple[str, np.ndarray]] = [
            ("gray", gray),
            ("clahe", clahe),
            ("adaptive", adaptive),
            ("otsu", otsu),
            ("upscale_gray_x2", cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)),
            ("upscale_clahe_x2", cv2.resize(clahe, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)),
            (
                "upscale_adaptive_x2",
                cv2.resize(adaptive, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST),
            ),
            (
                "upscale_otsu_x2",
                cv2.resize(otsu, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST),
            ),
            (
                "clahe_then_otsu",
                cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            ),
        ]
        return variants

    def _evaluate_variant(self, variant_name: str, detections: Sequence[Tuple[Any, str, float]]) -> Dict[str, Any]:
        lines, line_confs = self._group_to_lines(detections)
        top_line = lines[0] if lines else ""
        bottom_line = lines[1] if len(lines) > 1 else ""

        plate_candidate = self._normalize_plate(top_line)
        province_candidate = normalize_province(bottom_line)

        avg_conf = float(np.mean(line_confs)) if line_confs else 0.0

        score = avg_conf * 0.55
        if is_valid_plate(plate_candidate):
            score += 0.35
        elif plate_candidate:
            score += 0.15
        if province_candidate:
            score += 0.10

        return {
            "variant": variant_name,
            "plate_text": plate_candidate,
            "province": province_candidate,
            "score": score,
            "lines": lines,
            "candidates": [
                {
                    "plate_candidate": plate_candidate,
                    "province_candidate": province_candidate,
                    "avg_conf": avg_conf,
                    "valid_plate": is_valid_plate(plate_candidate),
                    "score": score,
                }
            ],
        }

    def _group_to_lines(self, detections: Sequence[Tuple[Any, str, float]]) -> Tuple[List[str], List[float]]:
        if not detections:
            return [], []

        rows: List[Tuple[float, str, float]] = []
        for box, text, conf in detections:
            if not text:
                continue
            y_center = float(np.mean([pt[1] for pt in box]))
            cleaned = re.sub(r"\s+", "", text)
            if not cleaned:
                continue
            rows.append((y_center, cleaned, float(conf or 0.0)))

        if not rows:
            return [], []

        rows.sort(key=lambda r: r[0])
        y_values = [r[0] for r in rows]
        spread = max(y_values) - min(y_values)
        threshold = max(8.0, spread * 0.25)

        clusters: List[List[Tuple[float, str, float]]] = []
        for item in rows:
            if not clusters:
                clusters.append([item])
                continue
            current_mean = float(np.mean([x[0] for x in clusters[-1]]))
            if abs(item[0] - current_mean) <= threshold:
                clusters[-1].append(item)
            else:
                clusters.append([item])

        clusters = sorted(clusters, key=lambda c: np.mean([x[0] for x in c]))[:2]
        lines: List[str] = []
        confs: List[float] = []
        for cluster in clusters:
            lines.append("".join([x[1] for x in cluster]))
            confs.append(float(np.mean([x[2] for x in cluster])))
        return lines, confs

    def _normalize_plate(self, text: str) -> str:
        norm = (text or "").strip()
        norm = norm.translate(_THAI_DIGIT_MAP)
        norm = re.sub(r"[\s\-_.]", "", norm)
        norm = re.sub(r"[^0-9ก-๙]", "", norm)
        return norm
