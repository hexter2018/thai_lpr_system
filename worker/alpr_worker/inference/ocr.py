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
<<<<<<< HEAD
_PLATE_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮ0123456789"
_PROVINCE_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ"
_PLATE_PATTERN = re.compile(r"^\d{0,2}[ก-ฮ]{1,2}\d{1,4}$")

try:
    from rapidfuzz import process as rapid_process  # type: ignore
except Exception:  # pragma: no cover
    rapid_process = None
=======
_THAI_ALLOWLIST = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะาำิีึืุูเแโใไั่้๊๋์ฯ0123456789"
_PLATE_FULL_RE = re.compile(r"^\d[ก-ฮ]{1,2}\d{4}$")
_PLATE_FALLBACK_RE = re.compile(r"^[ก-ฮ]{2}\d{4}$")
>>>>>>> parent of 4e73038 (Merge pull request #11 from hexter2018/codex/fix-tensorrt-build-and-improve-ocr-accuracy)


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

<<<<<<< HEAD
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
=======
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
>>>>>>> parent of 4e73038 (Merge pull request #11 from hexter2018/codex/fix-tensorrt-build-and-improve-ocr-accuracy)
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

<<<<<<< HEAD
        best = max(all_candidates, key=lambda c: c["score"], default={"text": "", "conf": 0.0, "score": 0.0})
        left = self._detect_left_digit(image)
=======
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
>>>>>>> parent of 4e73038 (Merge pull request #11 from hexter2018/codex/fix-tensorrt-build-and-improve-ocr-accuracy)

        merged = best["text"]
        forced = False
        if left and merged and not re.match(r"^\d", merged):
            merged = f"{left}{merged}"
            forced = True
        elif left and not merged:
            merged = left
            forced = True

<<<<<<< HEAD
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
=======
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
>>>>>>> parent of 4e73038 (Merge pull request #11 from hexter2018/codex/fix-tensorrt-build-and-improve-ocr-accuracy)

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
<<<<<<< HEAD

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
=======
>>>>>>> parent of 4e73038 (Merge pull request #11 from hexter2018/codex/fix-tensorrt-build-and-improve-ocr-accuracy)
