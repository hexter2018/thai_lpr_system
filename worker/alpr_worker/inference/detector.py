import os
import uuid
import logging
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
        # Prevent Ultralytics from trying runtime package installs inside containers.
        os.environ.setdefault("ULTRALYTICS_AUTOINSTALL", "false")

        self.model_path = os.getenv("MODEL_PATH", "").strip()
        self.log = logging.getLogger(__name__)
        self.storage_dir = Path(os.getenv("STORAGE_DIR", "/storage"))
        self.crop_dir = self.storage_dir / "crops"
        self.crop_dir.mkdir(parents=True, exist_ok=True)

        self.conf = float(os.getenv("DETECTOR_CONF", "0.35"))
        self.iou = float(os.getenv("DETECTOR_IOU", "0.45"))
        self.imgsz = int(os.getenv("DETECTOR_IMGSZ", "640"))
        self.class_id = int(os.getenv("DETECTOR_CLASS_ID", "0"))

        preferred_fallbacks = ["/models/best.engine", "/models/best.pt", "/models/best.onnx"]

        if self.model_path.endswith(".model_path") and Path(self.model_path).exists():
            resolved_model_path = Path(self.model_path).read_text().strip()
            if resolved_model_path:
                self.log.info("Resolved MODEL_PATH file %s -> %s", self.model_path, resolved_model_path)
                self.model_path = resolved_model_path

        if not self.model_path:
            # Try to find model automatically
            for fallback in preferred_fallbacks:
                if Path(fallback).exists():
                    self.model_path = fallback
                    break
            if not self.model_path:
                raise RuntimeError(
                    "MODEL_PATH is empty and no model found at /models/best.engine, /models/best.pt, or /models/best.onnx"
                )
        elif not Path(self.model_path).exists():
            for fallback in preferred_fallbacks:
                if Path(fallback).exists():
                    self.log.warning(
                        "Configured MODEL_PATH not found: %s. Falling back to %s",
                        self.model_path,
                        fallback,
                    )
                    self.model_path = fallback
                    break
            else:
                raise RuntimeError(f"MODEL_PATH not found: {self.model_path}. Available: check /models directory")

        # If TensorRT python bindings are not available, don't pass .engine into
        # Ultralytics because it triggers requirements auto-update attempts.
        if self.model_path.endswith(".engine"):
            try:
                import tensorrt  # type: ignore  # noqa: F401
            except ImportError:
                non_trt_fallbacks = ["/models/best.pt", "/models/best.onnx"]
                for fallback in non_trt_fallbacks:
                    if Path(fallback).exists():
                        self.log.warning(
                            "TensorRT python module unavailable; falling back from %s to %s",
                            self.model_path,
                            fallback,
                        )
                        self.model_path = fallback
                        break
                else:
                    raise RuntimeError(
                        "MODEL_PATH points to TensorRT engine but tensorrt module is unavailable, "
                        "and no /models/best.pt or /models/best.onnx fallback exists"
                    )

        # Import YOLO once (fast and stable)
        from ultralytics import YOLO
        self._yolo_cls = YOLO

        # IMPORTANT: Specify task explicitly
        self.yolo = self._load_yolo_model(self.model_path)

    def _find_non_engine_fallback(self) -> Optional[str]:
        for fallback in ["/models/best.pt", "/models/best.onnx"]:
            if Path(fallback).exists():
                return fallback
        return None

    def _load_yolo_model(self, model_path: str):
        try:
            return self._yolo_cls(model_path, task="detect")
        except Exception as e:
            # TensorRT engines can fail to deserialize if runtime version differs.
            # Gracefully fall back to .pt/.onnx when available.
            if model_path.endswith(".engine"):
                fallback = self._find_non_engine_fallback()
                if fallback:
                    self.log.warning(
                        "Failed to load TensorRT engine %s (%s). Falling back to %s",
                        model_path,
                        e,
                        fallback,
                    )
                    self.model_path = fallback
                    return self._yolo_cls(fallback, task="detect")
            raise


    def detect_and_crop(self, image_path: str) -> DetectionResult:
        img_path = Path(image_path)
        if not img_path.exists():
            raise RuntimeError(f"Image not found: {image_path}")

        # Fallback conf: ถ้า detect ไม่เจอที่ conf ปกติ ลองลด conf ลง
        fallback_conf = max(0.15, self.conf * 0.5)

        # Run prediction (works for .engine and .pt)
        try:
            results = self.yolo.predict(
                source=str(img_path),
                imgsz=self.imgsz,
                conf=self.conf,
                iou=self.iou,
                classes=[self.class_id],
                verbose=False,
                device=0,  # change if needed
            )
        except Exception as e:
            if self.model_path.endswith(".engine"):
                fallback = self._find_non_engine_fallback()
                if fallback:
                    self.log.warning(
                        "TensorRT inference failed using %s (%s). Retrying with %s",
                        self.model_path,
                        e,
                        fallback,
                    )
                    self.yolo = self._load_yolo_model(fallback)
                    results = self.yolo.predict(
                        source=str(img_path),
                        imgsz=self.imgsz,
                        conf=self.conf,
                        iou=self.iou,
                        classes=[self.class_id],
                        verbose=False,
                        device=0,
                    )
                else:
                    raise
            else:
                raise

        if not results or results[0] is None:
            raise RuntimeError("No YOLO results returned")

        r0 = results[0]
        if r0.boxes is None or len(r0.boxes) == 0:
            # FALLBACK: ลอง detect อีกครั้งที่ conf ต่ำลง
            if fallback_conf < self.conf:
                results = self.yolo.predict(
                    source=str(img_path),
                    imgsz=self.imgsz,
                    conf=fallback_conf,
                    iou=self.iou,
                    classes=[self.class_id],
                    verbose=False,
                    device=0,
                )
                if results and results[0] is not None:
                    r0 = results[0]
                    if r0.boxes is not None and len(r0.boxes) > 0:
                        import logging
                        logging.getLogger(__name__).info(
                            "FALLBACK detection succeeded at conf=%.2f (primary=%.2f)",
                            fallback_conf, self.conf
                        )

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
