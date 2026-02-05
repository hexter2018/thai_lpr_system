# worker/alpr_worker/inference/trt/yolov8_trt_detector.py

from __future__ import annotations

import os
import uuid
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

import cv2
import numpy as np

from .trt_runtime import TensorRTRuntime as TrtRuntime  # ต้องมีไฟล์ worker/alpr_worker/inference/trt/trt_runtime.py

log = logging.getLogger(__name__)


@dataclass
class TRTDetectionResult:
    crop_path: str
    det_conf: float
    bbox: Dict[str, Any]


# ----------------------------
# Utility: Letterbox
# ----------------------------
@dataclass
class LetterboxResult:
    img: np.ndarray
    ratio: float
    pad: Tuple[int, int]  # (pad_w, pad_h)


def letterbox(
    img: np.ndarray,
    new_shape: Tuple[int, int] = (640, 640),
    color: Tuple[int, int, int] = (114, 114, 114),
    auto: bool = False,
    scale_fill: bool = False,
    scale_up: bool = True,
) -> LetterboxResult:
    """
    Resize and pad image to meet new_shape (h,w), keeping aspect ratio.
    Returns padded image, scale ratio, and padding (dw, dh).
    """
    shape = img.shape[:2]  # (h, w)
    new_h, new_w = new_shape

    r = min(new_h / shape[0], new_w / shape[1])
    if not scale_up:
        r = min(r, 1.0)

    # compute unpadded size
    unpad_w = int(round(shape[1] * r))
    unpad_h = int(round(shape[0] * r))

    dw = new_w - unpad_w
    dh = new_h - unpad_h

    if auto:
        dw %= 32
        dh %= 32
    elif scale_fill:
        dw, dh = 0, 0
        unpad_w, unpad_h = new_w, new_h
        r = new_w / shape[1], new_h / shape[0]  # not used here

    dw //= 2
    dh //= 2

    if (shape[1], shape[0]) != (unpad_w, unpad_h):
        img = cv2.resize(img, (unpad_w, unpad_h), interpolation=cv2.INTER_LINEAR)

    top, bottom = dh, new_h - unpad_h - dh
    left, right = dw, new_w - unpad_w - dw
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)

    return LetterboxResult(img=img, ratio=r if isinstance(r, float) else float(r[0]), pad=(left, top))


# ----------------------------
# Utility: NMS
# ----------------------------
def box_iou_xyxy(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    IoU between two sets of boxes in xyxy.
    a: (N,4), b: (M,4)
    returns: (N,M)
    """
    # Intersection
    inter_x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    inter_y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    inter_x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    inter_y2 = np.minimum(a[:, None, 3], b[None, :, 3])

    inter_w = np.maximum(0.0, inter_x2 - inter_x1)
    inter_h = np.maximum(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h

    # Union
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-9)


def nms_xyxy(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> np.ndarray:
    """
    Classic NMS. boxes: (N,4) xyxy, scores: (N,)
    returns indices of kept boxes
    """
    if boxes.size == 0:
        return np.array([], dtype=np.int64)

    order = scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break

        ious = box_iou_xyxy(boxes[i:i+1], boxes[order[1:]])[0]
        inds = np.where(ious <= iou_thres)[0]
        order = order[inds + 1]

    return np.array(keep, dtype=np.int64)


# ----------------------------
# YOLOv8 TensorRT Detector
# ----------------------------
class YOLOv8TRTPlateDetector:
    """
    TensorRT direct detector for YOLOv8-style outputs.

    Env:
      MODEL_PATH=/models/best.engine
      STORAGE_DIR=/storage
      TRT_INPUT_W=640
      TRT_INPUT_H=640
      TRT_CONF_THRES=0.35
      TRT_IOU_THRES=0.45
      TRT_CLASS_ID=0
    """

    def __init__(self):
        self.model_path = os.getenv("MODEL_PATH", "/models/best.engine")
        self.storage_dir = Path(os.getenv("STORAGE_DIR", "/storage"))
        self.crop_dir = self.storage_dir / "crops"
        self.crop_dir.mkdir(parents=True, exist_ok=True)

        self.in_w = int(os.getenv("TRT_INPUT_W", "640"))
        self.in_h = int(os.getenv("TRT_INPUT_H", "640"))
        self.conf_thres = float(os.getenv("TRT_CONF_THRES", "0.35"))
        self.iou_thres = float(os.getenv("TRT_IOU_THRES", "0.45"))
        self.force_class_id = int(os.getenv("TRT_CLASS_ID", "0"))

        log.warning("Loading %s for TensorRT inference...", self.model_path)
        self.trt = TrtRuntime(self.model_path)  # must raise if cannot deserialize

        # Optional: warmup
        try:
            dummy = np.zeros((1, 3, self.in_h, self.in_w), dtype=np.float32)
            _ = self.trt.infer(dummy)
        except Exception as e:
            log.warning("TensorRT warmup failed (can ignore): %s", e)

    def _preprocess(self, bgr: np.ndarray) -> Tuple[np.ndarray, LetterboxResult]:
        lb = letterbox(bgr, new_shape=(self.in_h, self.in_w))
        img = lb.img

        # BGR -> RGB, float32 0..1, CHW
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[None, ...]  # 1,3,H,W
        return img, lb

    def _decode_outputs(self, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Return boxes_xyxy (N,4), scores (N,), class_ids (N,)

        Supports common YOLOv8 export shapes:
          - (1, N, 4+nc)
          - (1, 4+nc, N)
        Values usually in input-pixel units (0..W/H). If looks normalized (<=1.5),
        will scale by input size.
        """
        if y is None:
            raise RuntimeError("TensorRT returned None output")

        y = np.asarray(y)

        # Flatten batch if present
        if y.ndim == 3 and y.shape[0] == 1:
            y = y[0]

        # If output is (C, N), transpose -> (N, C)
        if y.ndim == 2:
            if y.shape[0] < y.shape[1] and y.shape[0] <= 256:
                # likely (C,N)
                y = y.T  # (N,C)
        elif y.ndim == 1:
            raise RuntimeError(f"Unexpected output shape: {y.shape}")
        else:
            # some engines output multiple tensors; TrtRuntime should return ndarray
            raise RuntimeError(f"Unexpected output ndim: {y.ndim}, shape={y.shape}")

        if y.shape[1] < 5:
            raise RuntimeError(f"Unexpected YOLO output last dim: {y.shape}")

        boxes_xywh = y[:, 0:4].astype(np.float32)
        cls_scores = y[:, 4:].astype(np.float32)

        # Choose class scores
        if cls_scores.shape[1] == 1:
            scores = cls_scores[:, 0]
            class_ids = np.zeros_like(scores, dtype=np.int32)
        else:
            class_ids = np.argmax(cls_scores, axis=1).astype(np.int32)
            scores = cls_scores[np.arange(cls_scores.shape[0]), class_ids]

        # optionally force one class (plate)
        if self.force_class_id >= 0 and cls_scores.shape[1] > 1:
            mask = class_ids == self.force_class_id
            boxes_xywh = boxes_xywh[mask]
            scores = scores[mask]
            class_ids = class_ids[mask]
        else:
            # for single-class models, already ok
            pass

        # Filter by confidence
        keep = scores >= self.conf_thres
        boxes_xywh = boxes_xywh[keep]
        scores = scores[keep]
        class_ids = class_ids[keep]

        if boxes_xywh.size == 0:
            return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.int32)

        # Convert xywh -> xyxy
        x, y0, w, h = boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
        x1 = x - w / 2
        y1 = y0 - h / 2
        x2 = x + w / 2
        y2 = y0 + h / 2
        boxes = np.stack([x1, y1, x2, y2], axis=1).astype(np.float32)

        # If normalized (0..1), scale to input dims
        # heuristic: if max coord <= 1.5 assume normalized
        if float(np.max(boxes)) <= 1.5:
            boxes[:, [0, 2]] *= float(self.in_w)
            boxes[:, [1, 3]] *= float(self.in_h)

        # Clip to input dims
        boxes[:, 0] = np.clip(boxes[:, 0], 0, self.in_w - 1)
        boxes[:, 1] = np.clip(boxes[:, 1], 0, self.in_h - 1)
        boxes[:, 2] = np.clip(boxes[:, 2], 0, self.in_w - 1)
        boxes[:, 3] = np.clip(boxes[:, 3], 0, self.in_h - 1)

        return boxes, scores, class_ids

    def _scale_boxes_back(
        self,
        boxes_xyxy: np.ndarray,
        lb: LetterboxResult,
        orig_shape: Tuple[int, int],
    ) -> np.ndarray:
        """
        Undo letterbox: map boxes from input (in_w,in_h) back to original image size.
        """
        if boxes_xyxy.size == 0:
            return boxes_xyxy

        pad_w, pad_h = lb.pad
        r = lb.ratio

        boxes = boxes_xyxy.copy()
        boxes[:, [0, 2]] -= pad_w
        boxes[:, [1, 3]] -= pad_h
        boxes[:, :4] /= max(r, 1e-9)

        h0, w0 = orig_shape
        boxes[:, 0] = np.clip(boxes[:, 0], 0, w0 - 1)
        boxes[:, 1] = np.clip(boxes[:, 1], 0, h0 - 1)
        boxes[:, 2] = np.clip(boxes[:, 2], 0, w0 - 1)
        boxes[:, 3] = np.clip(boxes[:, 3], 0, h0 - 1)
        return boxes

    def detect_and_crop(self, image_path: str) -> TRTDetectionResult:
        bgr0 = cv2.imread(image_path)
        if bgr0 is None:
            raise RuntimeError(f"Cannot read image: {image_path}")

        h0, w0 = bgr0.shape[:2]
        inp, lb = self._preprocess(bgr0)

        # TensorRT infer
        y = self.trt.infer(inp)

        # Decode
        boxes_inp, scores, class_ids = self._decode_outputs(y)

        if boxes_inp.size == 0:
            # fallback crop: return full image center crop for debugging (optional)
            # but better to raise for pipeline to mark as "no plate found"
            raise RuntimeError("No plate detected (after conf filter)")

        # NMS
        keep_idx = nms_xyxy(boxes_inp, scores, self.iou_thres)
        boxes_inp = boxes_inp[keep_idx]
        scores = scores[keep_idx]
        class_ids = class_ids[keep_idx]

        # pick best (highest score)
        best_i = int(np.argmax(scores))
        box_inp = boxes_inp[best_i:best_i+1]  # (1,4)
        score = float(scores[best_i])
        cid = int(class_ids[best_i])

        # map back to original image
        box_orig = self._scale_boxes_back(box_inp, lb, (h0, w0))[0]
        x1, y1, x2, y2 = [int(round(v)) for v in box_orig.tolist()]

        # Ensure valid crop region
        x1 = max(0, min(x1, w0 - 1))
        y1 = max(0, min(y1, h0 - 1))
        x2 = max(0, min(x2, w0 - 1))
        y2 = max(0, min(y2, h0 - 1))
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError(f"Invalid crop box: {(x1, y1, x2, y2)}")

        crop = bgr0[y1:y2, x1:x2]
        out_path = self.crop_dir / f"{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(out_path), crop)

        meta = {
            "xyxy": [x1, y1, x2, y2],
            "score": score,
            "class_id": cid,
            "input_wh": [self.in_w, self.in_h],
            "orig_wh": [w0, h0],
            "letterbox_ratio": lb.ratio,
            "letterbox_pad": [lb.pad[0], lb.pad[1]],
        }

        return TRTDetectionResult(
            crop_path=str(out_path),
            det_conf=score,
            bbox=meta,
        )
