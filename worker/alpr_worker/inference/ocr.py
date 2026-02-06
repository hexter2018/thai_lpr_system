from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import easyocr
import numpy as np
import torch

log = logging.getLogger(__name__)

_THAI_DIGIT_MAP = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_THAI_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ0123456789"
_PLATE_FULL_RE = re.compile(r"^\d[ก-ฮ]{1,2}\d{4}$")
_PLATE_FALLBACK_RE = re.compile(r"^[ก-ฮ]{2}\d{4}$")

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
            "recovery_applied": False,
            "candidates": [],
            "tokens": [],
            "confidence": 0.0,
        }

        for variant_name, variant_img in variants:
            detections = self.reader.readtext(variant_img, detail=1, allowlist=_THAI_ALLOWLIST)
            candidate = self._evaluate_variant(variant_name, detections)
            if candidate["score"] > best["score"]:
                best = candidate

        province_roi = self._read_province_from_roi(img)
        final_province = best["line_province"] or best["province"]
        if province_roi["province"]:
            final_province = province_roi["province"]
        
        return OCRResult(
            plate_text=best["plate_text"],
            province=final_province,
            confidence=max(0.0, min(float(best["confidence"]), 1.0)),
            raw={
                "chosen_variant": best["variant"],
                "lines": best["lines"],
                "line_province_score": best["line_province_score"],
                "roi_province": province_roi,
                "tokens": best["tokens"],
                "candidates": best["candidates"],
                "leading_digit_recovery": best["recovery_applied"],
            },
        )
    
    def _build_variants(self, image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(gray)
        sharpened = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))

        adaptive = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 4)
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

        lines, all_tokens = self._group_tokens_to_lines(detections)
        line_texts = ["".join(t["text"] for t in line) for line in lines]
        top_tokens = lines[0] if lines else []
        bottom_tokens = lines[1] if len(lines) > 1 else []
        plate_candidate, plate_confidence, recovery_applied, candidates = self._reconstruct_plate(top_tokens, bottom_tokens)

        bottom_line = line_texts[1] if len(line_texts) > 1 else ""
        line_province, line_province_score = match_province(bottom_line)
        merged_line_province, merged_score = match_province("".join(line_texts))
        if merged_score > line_province_score:
            line_province = merged_line_province
            line_province_score = merged_score
        score = plate_confidence
        if line_province:
            score += 0.08
        
        return {
            "variant": variant_name,
            "plate_text": plate_candidate,
            "province": normalize_province(bottom_line),
            "line_province": line_province,
            "line_province_score": line_province_score,
            "score": score,
            "confidence": plate_confidence,
            "lines": line_texts,
            "tokens": all_tokens,
            "candidates": candidates,
            "recovery_applied": recovery_applied,
        }
    
    def _reconstruct_plate(self, top_tokens: List[Dict[str, Any]], bottom_tokens: List[Dict[str, Any]]) -> Tuple[str, float, bool, List[Dict[str, Any]]]:
        candidates: List[Dict[str, Any]] = []

        def add_candidate(name: str, text: str, tokens: List[Dict[str, Any]], recovered: bool = False) -> None:
            norm_text = self._normalize_plate(text)
            if not norm_text:
                return
            confs = [float(t["conf"]) for t in tokens if t.get("text")]
            base_conf = float(np.mean(confs)) if confs else 0.0
            regex_bonus = 0.22 if _PLATE_FULL_RE.match(norm_text) else 0.12 if _PLATE_FALLBACK_RE.match(norm_text) else 0.0
            recovery_penalty = 0.08 if recovered else 0.0
            cand_score = base_conf + regex_bonus - recovery_penalty
            candidates.append(
                {
                    "name": name,
                    "text": norm_text,
                    "score": cand_score,
                    "base_conf": base_conf,
                    "regex_bonus": regex_bonus,
                    "recovered": recovered,
                    "token_count": len(tokens),
                }
            )

        top_text = "".join(t["text"] for t in top_tokens)
        bottom_text = "".join(t["text"] for t in bottom_tokens)
        add_candidate("top_line", top_text, top_tokens)
        add_candidate("top_plus_bottom", top_text + bottom_text, top_tokens + bottom_tokens)

        # Recover missing leading digit token (e.g., ขช5148 + isolated "4" on the left)
        recovery_applied = False
        for cand in list(candidates):
            if not _PLATE_FALLBACK_RE.match(cand["text"]):
                continue
            first_thai_x = min((t["x"] for t in top_tokens if re.search(r"[ก-ฮ]", t["text"] or "")), default=None)
            if first_thai_x is None:
                continue
            digit_tokens = [
                t
                for t in top_tokens
                if re.fullmatch(r"\d", t["text"] or "") and t["x"] < first_thai_x and float(t["conf"]) >= 0.35
            ]
            if not digit_tokens:
                continue
            digit_tokens.sort(key=lambda t: t["x"])
            recovered_text = "".join(t["text"] for t in digit_tokens) + cand["text"]
            add_candidate("leading_digit_recovery", recovered_text, digit_tokens + top_tokens, recovered=True)
            recovery_applied = True

        if not candidates:
            return "", 0.0, False, []

        candidates.sort(key=lambda c: (c["score"], 1 if _PLATE_FULL_RE.match(c["text"]) else 0), reverse=True)
        best = candidates[0]

        confidence = max(0.0, min(best["score"], 1.0))
        if _PLATE_FULL_RE.match(best["text"]):
            confidence = min(1.0, confidence + 0.06)

        return best["text"], confidence, bool(best["recovered"] or recovery_applied), candidates
    
    def _read_province_from_roi(self, image: np.ndarray) -> Dict[str, Any]:
        h, w = image.shape[:2]
        roi_ratios = [0.50, 0.40, 0.35]
        best_province = ""
        best_score = 0.0
        best_debug: Dict[str, Any] = {}

        for ratio in roi_ratios:
            start_y = int(h * (1.0 - ratio))
            roi = image[start_y:h, 0:w]
            if roi.size == 0:
                continue
            for variant_name, variant in self._build_province_roi_variants(roi):
                texts = self._read_text_tokens(self.thai_reader, variant, thai_only=True)
                if not texts:
                    continue
                candidates = ["".join(texts)] + texts
                for text in candidates:
                    province, score = match_province(text, threshold=58)
                    if score < 58:
                        thai_only_text = re.sub(r"[^ก-๙]", "", text)
                        province, score = match_province(thai_only_text, threshold=54)
                    province = normalize_province(province or text, threshold=54)
                    if province and score > best_score:
                        best_province = province
                        best_score = float(score)
                        best_debug = {
                            "roi_ratio": ratio,
                            "variant": variant_name,
                            "texts": texts,
                            "source_text": text,
                        }

        return {"province": best_province, "score": best_score, **best_debug}

    def _build_province_roi_variants(self, roi: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        upscaled = cv2.resize(gray, None, fx=2.6, fy=2.6, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=3.2, tileGridSize=(8, 8)).apply(upscaled)
        sharpen = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5.2, -1], [0, -1, 0]], dtype=np.float32))
        kernel = np.ones((2, 2), np.uint8)
        morph_close = cv2.morphologyEx(sharpen, cv2.MORPH_CLOSE, kernel, iterations=1)
        morph_open = cv2.morphologyEx(morph_close, cv2.MORPH_OPEN, kernel, iterations=1)

        adaptive = cv2.adaptiveThreshold(morph_open, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
        otsu = cv2.threshold(morph_open, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        return [
            ("gray_upscaled", upscaled),
            ("clahe", clahe),
            ("morph_open", morph_open),
            ("adaptive", adaptive),
            ("otsu", otsu),
        ]
    def _read_text_tokens(self, reader: easyocr.Reader, image: np.ndarray, thai_only: bool = False) -> List[str]:
        kwargs: Dict[str, Any] = {"detail": 1}
        if thai_only:
            kwargs["allowlist"] = _THAI_ALLOWLIST
        detections = reader.readtext(image, **kwargs)
        tokens: List[str] = []
        for _, text, conf in detections:
            if conf is None or float(conf) < 0.10:
                continue
            cleaned = self._normalize_plate(text or "")
            if cleaned:
                tokens.append(cleaned)
        return tokens
    
    def _group_tokens_to_lines(self, detections: Sequence[Tuple[Any, str, float]]) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        rows: List[Dict[str, Any]] = []
        for box, text, conf in detections:
            cleaned = self._normalize_plate(text or "")
            if not cleaned:
                continue
            y_center = float(np.mean([pt[1] for pt in box]))
            x_center = float(np.mean([pt[0] for pt in box]))
            rows.append(
                {
                    "bbox": [[float(pt[0]), float(pt[1])] for pt in box],
                    "text": cleaned,
                    "conf": float(conf or 0.0),
                    "x": x_center,
                    "y": y_center,
                }
            )
    
        if not rows:
            return [], []
        rows.sort(key=lambda r: r["y"])
        y_values = [r["y"] for r in rows]
        spread = max(y_values) - min(y_values)
        threshold = max(8.0, spread * 0.22)
        clusters: List[List[Dict[str, Any]]] = []
        for item in rows:
            if not clusters:
                clusters.append([item])
                continue
            current_mean = float(np.mean([x["y"] for x in clusters[-1]]))
            if abs(item["y"] - current_mean) <= threshold:
                clusters[-1].append(item)
            else:
                clusters.append([item])
        clusters = sorted(clusters, key=lambda c: np.mean([x["y"] for x in c]))[:2]
        for cluster in clusters:
            cluster.sort(key=lambda c: c["x"])
        return clusters, rows
    def _normalize_plate(self, text: str) -> str:
        norm = (text or "").strip()
        norm = norm.translate(_THAI_DIGIT_MAP)
        norm = re.sub(r"[\s\-_.]", "", norm)
        norm = re.sub(r"[^0-9ก-๙]", "", norm)
        return norm