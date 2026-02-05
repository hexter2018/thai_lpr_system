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
_THAI_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ0123456789"


@dataclass
class OCRResult:
    plate_text: str
    province: str
    confidence: float
    raw: Dict[str, Any]


class PlateOCR:
    """EasyOCR pipeline for Thai plate + province extraction."""

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

        variants = self._build_variants(img)
        best: Dict[str, Any] = {
            "plate_text": "",
            "province": "",
            "score": 0.0,
            "variant": "",
            "lines": [],
            "line_province": "",
            "line_province_score": 0.0,
        }

        for variant_name, variant_img in variants:
            detections = self.reader.readtext(variant_img, detail=1, allowlist=_THAI_ALLOWLIST)
            candidate = self._evaluate_variant(variant_name, detections)
            if candidate["score"] > best["score"]:
                best = candidate

        province_roi = self._read_province_from_roi(img)

        final_province = best["line_province"]
        if province_roi["province"]:
            final_province = province_roi["province"]
        elif best["province"]:
            final_province = best["province"]

        confidence = max(0.0, min(float(best["score"]), 1.0))
        return OCRResult(
            plate_text=best["plate_text"],
            province=final_province,
            confidence=confidence,
            raw={
                "chosen_variant": best["variant"],
                "lines": best["lines"],
                "line_province_score": best["line_province_score"],
                "roi_province": province_roi,
            },
        )

    def _build_variants(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(gray)
        sharpened = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))
        adaptive = cv2.adaptiveThreshold(
            sharpened,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            4,
        )
        otsu = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        return [
            ("gray", gray),
            ("clahe", clahe),
            ("sharpened", sharpened),
            ("adaptive", adaptive),
            ("otsu", otsu),
            ("upscale_sharpened_x2", cv2.resize(sharpened, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)),
            ("upscale_adaptive_x2", cv2.resize(adaptive, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)),
        ]

    def _evaluate_variant(self, variant_name: str, detections: Sequence[Tuple[Any, str, float]]) -> Dict[str, Any]:
        lines, line_confs = self._group_to_lines(detections)
        top_line = lines[0] if lines else ""
        bottom_line = lines[1] if len(lines) > 1 else ""

        plate_candidate = self._normalize_plate(top_line)
        line_province, line_province_score = match_province(bottom_line)

        # Fallback: merge all lines to capture broken province tokens.
        merged_line_province, merged_score = match_province("".join(lines))
        if merged_score > line_province_score:
            line_province = merged_line_province
            line_province_score = merged_score

        avg_conf = float(np.mean(line_confs)) if line_confs else 0.0

        score = avg_conf * 0.55
        if is_valid_plate(plate_candidate):
            score += 0.35
        elif plate_candidate:
            score += 0.15
        if line_province:
            score += 0.10

        return {
            "variant": variant_name,
            "plate_text": plate_candidate,
            "province": normalize_province(bottom_line),
            "line_province": line_province,
            "line_province_score": line_province_score,
            "score": score,
            "lines": lines,
        }

    def _read_province_from_roi(self, image: np.ndarray) -> Dict[str, Any]:
        h, w = image.shape[:2]
        start_y = int(h * 0.55)
        roi = image[start_y:h, 0:w]
        if roi.size == 0:
            return {"province": "", "score": 0.0, "texts": []}

        roi_variants = self._build_province_roi_variants(roi)
        best_province = ""
        best_score = 0.0
        best_texts: List[str] = []

        for variant in roi_variants:
            texts = self._read_text_tokens(self.thai_reader, variant, thai_only=True)
            if not texts:
                continue
            candidates = ["".join(texts)] + texts
            for text in candidates:
                province, score = match_province(text, threshold=58)
                if province and score > best_score:
                    best_province = province
                    best_score = score
                    best_texts = texts

        return {"province": best_province, "score": best_score, "texts": best_texts}

    def _build_province_roi_variants(self, roi: np.ndarray) -> List[np.ndarray]:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        upscaled = cv2.resize(gray, None, fx=2.6, fy=2.6, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=3.2, tileGridSize=(8, 8)).apply(upscaled)
        sharpen = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5.2, -1], [0, -1, 0]], dtype=np.float32))
        adaptive = cv2.adaptiveThreshold(sharpen, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 3)
        inverse = cv2.bitwise_not(adaptive)
        return [upscaled, clahe, sharpen, adaptive, inverse]

    def _read_text_tokens(self, reader: easyocr.Reader, image: np.ndarray, thai_only: bool = False) -> List[str]:
        kwargs: Dict[str, Any] = {"detail": 1}
        if thai_only:
            kwargs["allowlist"] = _THAI_ALLOWLIST
        detections = reader.readtext(image, **kwargs)
        tokens: List[str] = []
        for _, text, conf in detections:
            if conf is None or float(conf) < 0.10:
                continue
            cleaned = re.sub(r"\s+", "", text or "")
            if cleaned:
                tokens.append(cleaned)
        return tokens

    def _group_to_lines(self, detections: Sequence[Tuple[Any, str, float]]) -> Tuple[List[str], List[float]]:
        if not detections:
            return [], []

        rows: List[Tuple[float, float, str, float]] = []
        for box, text, conf in detections:
            if not text:
                continue
            y_center = float(np.mean([pt[1] for pt in box]))
            x_center = float(np.mean([pt[0] for pt in box]))
            cleaned = re.sub(r"\s+", "", text)
            if not cleaned:
                continue
            rows.append((y_center, x_center, cleaned, float(conf or 0.0)))

        if not rows:
            return [], []

        rows.sort(key=lambda r: r[0])
        y_values = [r[0] for r in rows]
        spread = max(y_values) - min(y_values)
        threshold = max(8.0, spread * 0.24)

        clusters: List[List[Tuple[float, float, str, float]]] = []
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
            by_x = sorted(cluster, key=lambda c: c[1])
            lines.append("".join([x[2] for x in by_x]))
            confs.append(float(np.mean([x[3] for x in by_x])))
        return lines, confs

    def _normalize_plate(self, text: str) -> str:
        norm = (text or "").strip()
        norm = norm.translate(_THAI_DIGIT_MAP)
        norm = re.sub(r"[\s\-_.]", "", norm)
        norm = re.sub(r"[^0-9ก-๙]", "", norm)
        return norm
