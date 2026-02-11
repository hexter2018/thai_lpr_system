import os
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import cv2


@dataclass
class DetectionResult:
    crop_path: str
    det_conf: float
    bbox: dict


class PlateDetector:
    """
    Production detector using Ultralytics YOLO wrapper.
    - Supports MODEL_PATH = .engine (TensorRT) or .pt (PyTorch)
    - ULTRALYTICS_AUTOINSTALL must be "false" in production
    """
    def __init__(self):
        self.model_path = os.getenv("MODEL_PATH", "").strip()
        self.storage_dir = Path(os.getenv("STORAGE_DIR", "/storage"))
        self.crop_dir = self.storage_dir / "crops"
        self.crop_dir.mkdir(parents=True, exist_ok=True)

        self.conf = float(os.getenv("DETECTOR_CONF", "0.35"))
        self.iou = float(os.getenv("DETECTOR_IOU", "0.45"))
        self.imgsz = int(os.getenv("DETECTOR_IMGSZ", "640"))
        self.class_id = int(os.getenv("DETECTOR_CLASS_ID", "0"))

        if not self.model_path:
            # Try to find model automatically
            for fallback in ["/models/best.engine", "/models/best.pt"]:
                if Path(fallback).exists():
                    self.model_path = fallback
                    break
            if not self.model_path:
                raise RuntimeError("MODEL_PATH is empty and no model found at /models/best.engine or /models/best.pt")

        if not Path(self.model_path).exists():
            raise RuntimeError(f"MODEL_PATH not found: {self.model_path}. Available: check /models directory")

        # Import YOLO once (fast and stable)
        from ultralytics import YOLO

        # IMPORTANT: Specify task explicitly
        self.yolo = YOLO(self.model_path, task="detect")

    def detect_and_crop(self, image_path: str) -> DetectionResult:
        img_path = Path(image_path)
        if not img_path.exists():
            raise RuntimeError(f"Image not found: {image_path}")

        # Run prediction (works for .engine and .pt)
        results = self.yolo.predict(
            source=str(img_path),
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            classes=[self.class_id],
            verbose=False,
            device=0,  # change if needed
        )

        if not results or results[0] is None:
            raise RuntimeError("No YOLO results returned")

        r0 = results[0]
        if r0.boxes is None or len(r0.boxes) == 0:
            raise RuntimeError("No plate detected")

        # pick the best box by confidence
        boxes = r0.boxes
        confs = boxes.conf.tolist()
        best_i = int(max(range(len(confs)), key=lambda i: confs[i]))

        xyxy = boxes.xyxy[best_i].tolist()
        score = float(boxes.conf[best_i].item())

        x1, y1, x2, y2 = [int(round(v)) for v in xyxy]

        # load original image for cropping
        bgr = cv2.imread(str(img_path))
        if bgr is None:
            raise RuntimeError(f"Cannot read image: {image_path}")

        h, w = bgr.shape[:2]
        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))

        if x2 <= x1 or y2 <= y1:
            raise RuntimeError(f"Invalid crop box: {(x1, y1, x2, y2)}")

        crop = bgr[y1:y2, x1:x2]
        out_path = self.crop_dir / f"{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(out_path), crop)

        meta = {
            "xyxy": [x1, y1, x2, y2],
            "score": score,
            "model_path": self.model_path,
            "imgsz": self.imgsz,
        }

        return DetectionResult(
            crop_path=str(out_path),
            det_conf=score,
            bbox=meta,
        )
