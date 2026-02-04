# lpr_processor.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import cv2
import numpy as np

from ultralytics import YOLO
from paddleocr import PaddleOCR

from thefuzz import process as fuzz_process
from thefuzz import fuzz


THAI_PROVINCES: List[str] = [
    "กรุงเทพมหานคร","กระบี่","กาญจนบุรี","กาฬสินธุ์","กำแพงเพชร","ขอนแก่น","จันทบุรี","ฉะเชิงเทรา",
    "ชลบุรี","ชัยนาท","ชัยภูมิ","ชุมพร","เชียงราย","เชียงใหม่","ตรัง","ตราด","ตาก","นครนายก",
    "นครปฐม","นครพนม","นครราชสีมา","นครศรีธรรมราช","นครสวรรค์","นนทบุรี","นราธิวาส","น่าน",
    "บึงกาฬ","บุรีรัมย์","ปทุมธานี","ประจวบคีรีขันธ์","ปราจีนบุรี","ปัตตานี","พระนครศรีอยุธยา",
    "พะเยา","พังงา","พัทลุง","พิจิตร","พิษณุโลก","เพชรบุรี","เพชรบูรณ์","แพร่","ภูเก็ต",
    "มหาสารคาม","มุกดาหาร","แม่ฮ่องสอน","ยะลา","ยโสธร","ร้อยเอ็ด","ระนอง","ระยอง","ราชบุรี",
    "ลพบุรี","ลำปาง","ลำพูน","เลย","ศรีสะเกษ","สกลนคร","สงขลา","สตูล","สมุทรปราการ","สมุทรสงคราม",
    "สมุทรสาคร","สระแก้ว","สระบุรี","สิงห์บุรี","สุโขทัย","สุพรรณบุรี","สุราษฎร์ธานี","สุรินทร์",
    "หนองคาย","หนองบัวลำภู","อ่างทอง","อำนาจเจริญ","อุดรธานี","อุตรดิตถ์","อุทัยธานี","อุบลราชธานี"
]


@dataclass
class LPRResult:
    license_text: str
    province: str
    confidence: float
    cropped_image: np.ndarray


class LPRProcessor:
    """
    Plate detection (YOLOv8 .engine preferred) + PaddleOCR Thai + parsing + province fuzzy match.
    Intended for NVIDIA GPU (e.g., GTX3060).
    """

    def __init__(
        self,
        model_dir: str = "../models",
        model_name_pt: str = "best.pt",
        model_name_engine: str = "best.engine",
        device: str = "cuda:0",
        det_conf: float = 0.25,
        det_iou: float = 0.5,
        crop_padding_ratio: float = 0.05,
        province_match_threshold: int = 75,
    ) -> None:
        self.model_dir = model_dir
        self.model_path_engine = os.path.join(model_dir, model_name_engine)
        self.model_path_pt = os.path.join(model_dir, model_name_pt)
        self.device = device
        self.det_conf = det_conf
        self.det_iou = det_iou
        self.crop_padding_ratio = crop_padding_ratio
        self.province_match_threshold = province_match_threshold

        self.model = self._load_yolo()
        self.ocr = self._load_ocr()

    def _load_yolo(self) -> YOLO:
        if os.path.exists(self.model_path_engine):
            # Ultralytics can load TensorRT engine directly
            return YOLO(self.model_path_engine)
        if not os.path.exists(self.model_path_pt):
            raise FileNotFoundError(f"Model not found: {self.model_path_pt}")
        return YOLO(self.model_path_pt)

    def _load_ocr(self) -> PaddleOCR:
        # PaddleOCR language: "thai" (Thai support). Use GPU.
        # If you also need English, consider lang="th" vs "thai" depending on your PaddleOCR version.
        return PaddleOCR(
            lang="thai",
            use_angle_cls=True,
            use_gpu=True,
            show_log=False,
        )

    def recognize(self, image_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Input: image as numpy array (BGR).
        Output dict: license_text, province, confidence, cropped_image (np.ndarray)
        """
        box, det_score = self._detect_best_plate(image_bgr)
        if box is None:
            return {
                "license_text": "",
                "province": "",
                "confidence": 0.0,
                "cropped_image": None,
            }

        crop = self._crop_with_padding(image_bgr, box, self.crop_padding_ratio)
        ocr_texts, ocr_scores = self._run_ocr(crop)

        parsed_license, raw_province = self._parse_text(ocr_texts)
        province = self._fuzzy_province(raw_province)

        # Combine confidence conservatively: detection * avg_ocr_conf
        avg_ocr = float(np.mean(ocr_scores)) if ocr_scores else 0.0
        combined_conf = float(det_score) * avg_ocr

        return {
            "license_text": parsed_license.strip(),
            "province": province.strip(),
            "confidence": combined_conf,
            "cropped_image": crop,
            "debug": {
                "det_conf": float(det_score),
                "ocr_texts": ocr_texts,
                "ocr_avg_conf": avg_ocr,
                "raw_province": raw_province,
            },
        }

    def _detect_best_plate(self, image_bgr: np.ndarray) -> Tuple[Optional[Tuple[int,int,int,int]], float]:
        # Ultralytics expects RGB or BGR; it handles numpy. We'll keep BGR.
        results = self.model.predict(
            source=image_bgr,
            conf=self.det_conf,
            iou=self.det_iou,
            verbose=False,
            device=0,   # cuda:0
        )
        if not results or len(results) == 0:
            return None, 0.0

        r0 = results[0]
        if r0.boxes is None or len(r0.boxes) == 0:
            return None, 0.0

        # Pick the highest confidence box
        boxes = r0.boxes
        confs = boxes.conf.detach().cpu().numpy()
        xyxy = boxes.xyxy.detach().cpu().numpy()

        best_i = int(np.argmax(confs))
        x1, y1, x2, y2 = xyxy[best_i]
        return (int(x1), int(y1), int(x2), int(y2)), float(confs[best_i])

    def _crop_with_padding(
        self,
        image_bgr: np.ndarray,
        box: Tuple[int,int,int,int],
        pad_ratio: float
    ) -> np.ndarray:
        h, w = image_bgr.shape[:2]
        x1, y1, x2, y2 = box

        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        pad_x = int(bw * pad_ratio)
        pad_y = int(bh * pad_ratio)

        nx1 = max(0, x1 - pad_x)
        ny1 = max(0, y1 - pad_y)
        nx2 = min(w - 1, x2 + pad_x)
        ny2 = min(h - 1, y2 + pad_y)

        crop = image_bgr[ny1:ny2, nx1:nx2].copy()
        return crop

    def _run_ocr(self, crop_bgr: np.ndarray) -> Tuple[List[str], List[float]]:
        # PaddleOCR works better with RGB
        crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        ocr_result = self.ocr.ocr(crop_rgb, cls=True)

        texts: List[str] = []
        scores: List[float] = []

        # PaddleOCR output shape varies by version; handle robustly
        if not ocr_result:
            return texts, scores

        # Usually: [ [ [box], (text, score) ], ... ]
        for line in ocr_result[0] if isinstance(ocr_result, list) and len(ocr_result) > 0 else []:
            if not line or len(line) < 2:
                continue
            txt, sc = line[1]
            if txt:
                texts.append(str(txt).strip())
                scores.append(float(sc))

        return texts, scores

    def _normalize(self, s: str) -> str:
        s = s.strip()
        s = re.sub(r"\s+", "", s)
        s = s.replace("-", "")
        return s

    def _parse_text(self, ocr_texts: List[str]) -> Tuple[str, str]:
        """
        CRITICAL post-processing:
        - Separate into Category (e.g., 1กก), Number (e.g., 1234), Province
        Heuristic:
        - Province is usually the longest Thai word OR bottom line; we fuzzy-match later anyway.
        """
        if not ocr_texts:
            return "", ""

        # Keep original order as OCR gives (often top-to-bottom).
        cleaned = [t.strip() for t in ocr_texts if t and t.strip()]
        if not cleaned:
            return "", ""

        # Candidate province: pick the text with the most Thai letters and length
        def thai_letter_count(x: str) -> int:
            return len(re.findall(r"[ก-ฮ]", x))

        province_candidate = max(cleaned, key=lambda x: (thai_letter_count(x), len(x)))

        # The remaining texts likely contain plate category+number
        others = [t for t in cleaned if t != province_candidate]
        joined = self._normalize("".join(others)) if others else self._normalize(cleaned[0])

        # Extract category and number
        # Category often like: 1กก, 2ขก, etc.
        cat_match = re.search(r"([0-9]{1,2}[ก-ฮ]{1,3})", joined)
        num_match = re.search(r"([0-9]{1,4})", joined)

        category = cat_match.group(1) if cat_match else ""
        number = ""
        if num_match:
            # Ensure we are not reusing digits from category; just take last digits occurrence
            nums = re.findall(r"([0-9]{1,4})", joined)
            number = nums[-1] if nums else num_match.group(1)

        license_text = (category + " " + number).strip()
        return license_text, province_candidate

    def _fuzzy_province(self, raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""

        # Normalize common OCR mistakes (optional quick fixes)
        raw_norm = raw.replace("กทม", "กรุงเทพมหานคร").replace("กรุงเทพ", "กรุงเทพมหานคร")

        match = fuzz_process.extractOne(raw_norm, THAI_PROVINCES, scorer=fuzz.ratio)
        if not match:
            return raw_norm

        best_name, score = match[0], int(match[1])
        if score >= self.province_match_threshold:
            return best_name
        return raw_norm
