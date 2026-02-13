"""
vehicle_detector.py — YOLO-based Vehicle Detection for Zone Capture
====================================================================

ใช้ YOLO model (.pt) ตรวจจับรถยนต์ใน frame
แล้วเช็คว่า bounding box ของรถทับกับ CaptureZone หรือไม่
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

_DEFAULT_VEHICLE_CLASSES = {2, 3, 5, 7}
_CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 0: "person"}
_CLASS_COLORS = {2: (0, 200, 80), 3: (0, 180, 255), 5: (255, 100, 0), 7: (180, 0, 255)}
_DEFAULT_COLOR = (200, 200, 0)


@dataclass
class VehicleDetection:
    bbox: Tuple[int, int, int, int]
    confidence: float
    class_id: int
    class_name: str
    track_id: Optional[int] = None
    zone_name: Optional[str] = None
    zone_overlap: float = 0.0

    @property
    def center(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)


@dataclass
class ZoneDetectionResult:
    detections: List[VehicleDetection]
    zone_detections: Dict[str, List[VehicleDetection]]
    triggered_zones: List[str]
    annotated_frame: Optional[np.ndarray] = None
    inference_ms: float = 0.0


def _bbox_polygon_overlap(
    bbox: Tuple[int, int, int, int],
    polygon_px: np.ndarray,
    frame_shape: Tuple[int, int],
) -> float:
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = bbox

    zone_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(zone_mask, [polygon_px], 255)

    bbox_mask = np.zeros((h, w), dtype=np.uint8)
    bx1, by1 = max(0, x1), max(0, y1)
    bx2, by2 = min(w, x2), min(h, y2)
    if bx2 <= bx1 or by2 <= by1:
        return 0.0
    bbox_mask[by1:by2, bx1:bx2] = 255

    intersection = cv2.bitwise_and(zone_mask, bbox_mask)
    inter_pixels = int(np.count_nonzero(intersection))
    bbox_pixels = int(np.count_nonzero(bbox_mask))

    if bbox_pixels == 0:
        return 0.0
    return inter_pixels / bbox_pixels


class VehicleDetector:
    def __init__(self):
        self.enabled = os.getenv("VEHICLE_DETECTOR_ENABLED", "true").lower() == "true"
        self.model_path = os.getenv("VEHICLE_DETECTOR_MODEL_PATH", "").strip()
        self.conf = float(os.getenv("VEHICLE_DETECTOR_CONF", "0.40"))
        self.iou = float(os.getenv("VEHICLE_DETECTOR_IOU", "0.45"))
        self.imgsz = int(os.getenv("VEHICLE_DETECTOR_IMGSZ", "640"))
        self.device = os.getenv("VEHICLE_DETECTOR_DEVICE", "0")
        self.min_zone_overlap = float(os.getenv("VEHICLE_DETECTOR_MIN_ZONE_OVERLAP", "0.20"))

        classes_raw = os.getenv("VEHICLE_DETECTOR_CLASSES", "2,3,5,7")
        try:
            self.vehicle_classes = set(int(c.strip()) for c in classes_raw.split(","))
        except ValueError:
            self.vehicle_classes = _DEFAULT_VEHICLE_CLASSES

        self._model = None
        self._load_error: Optional[str] = None

        if self.enabled:
            self._load_model()

    def _load_model(self):
        if not self.model_path:
            for fallback in ["/models/vehicle.pt", "/models/yolov8n.pt", "/models/best.pt"]:
                if Path(fallback).exists():
                    self.model_path = fallback
                    break

        if not self.model_path:
            self._load_error = "No vehicle model found (set VEHICLE_DETECTOR_MODEL_PATH)"
            log.warning("VehicleDetector: %s", self._load_error)
            return

        if not Path(self.model_path).exists():
            self._load_error = f"Model not found: {self.model_path}"
            log.error("VehicleDetector: %s", self._load_error)
            return

        try:
            from ultralytics import YOLO

            self._model = YOLO(self.model_path, task="detect")
            dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            self._model.predict(dummy, imgsz=self.imgsz, verbose=False)
        except Exception as exc:
            self._load_error = str(exc)
            log.error("VehicleDetector: model load failed: %s", exc)
            self._model = None

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def detect(self, frame: np.ndarray) -> List[VehicleDetection]:
        if not self.enabled or self._model is None:
            return []

        try:
            try:
                device = int(self.device)
            except ValueError:
                device = self.device

            results = self._model.predict(
                source=frame,
                imgsz=self.imgsz,
                conf=self.conf,
                iou=self.iou,
                classes=list(self.vehicle_classes),
                verbose=False,
                device=device,
            )
        except Exception as exc:
            log.warning("VehicleDetector inference error: %s", exc)
            return []

        if not results or results[0] is None or results[0].boxes is None:
            return []

        detections: List[VehicleDetection] = []
        for box in results[0].boxes:
            cls_id = int(box.cls[0].item())
            if cls_id not in self.vehicle_classes:
                continue

            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = (int(round(v)) for v in xyxy)

            track_id = None
            if hasattr(box, "id") and box.id is not None:
                track_id = int(box.id[0].item())

            detections.append(
                VehicleDetection(
                    bbox=(x1, y1, x2, y2),
                    confidence=conf,
                    class_id=cls_id,
                    class_name=_CLASS_NAMES.get(cls_id, f"class_{cls_id}"),
                    track_id=track_id,
                )
            )
        return detections

    def detect_in_zones(self, frame: np.ndarray, zones, draw: bool = True) -> ZoneDetectionResult:
        t0 = time.perf_counter()
        detections = self.detect(frame)
        inference_ms = (time.perf_counter() - t0) * 1000

        h, w = frame.shape[:2]
        zone_detections: Dict[str, List[VehicleDetection]] = {z.name: [] for z in zones}
        triggered_zones: List[str] = []

        for det in detections:
            best_zone: Optional[str] = None
            best_overlap = 0.0
            for zone in zones:
                pts = zone.pixel_points(w, h)
                overlap = _bbox_polygon_overlap(det.bbox, pts, frame.shape)
                if overlap >= self.min_zone_overlap and overlap > best_overlap:
                    best_overlap = overlap
                    best_zone = zone.name

            if best_zone:
                det.zone_name = best_zone
                det.zone_overlap = best_overlap
                zone_detections[best_zone].append(det)

        for zone in zones:
            if zone_detections.get(zone.name):
                triggered_zones.append(zone.name)

        annotated = self._draw_detections(frame.copy(), detections, zones) if draw else None
        return ZoneDetectionResult(
            detections=detections,
            zone_detections=zone_detections,
            triggered_zones=triggered_zones,
            annotated_frame=annotated,
            inference_ms=inference_ms,
        )

    def _draw_detections(self, frame: np.ndarray, detections: List[VehicleDetection], zones=None) -> np.ndarray:
        h, w = frame.shape[:2]
        if zones:
            for zone in zones:
                pts = zone.pixel_points(w, h)
                overlay = frame.copy()
                cv2.fillPoly(overlay, [pts], (30, 60, 30))
                cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)
                cv2.polylines(frame, [pts], True, (0, 220, 80), 2)

        for det in detections:
            x1, y1, x2, y2 = det.bbox
            color = _CLASS_COLORS.get(det.class_id, _DEFAULT_COLOR)
            thickness = 2 if det.zone_name else 1
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

            label = f"{det.class_name} {det.confidence:.0%}"
            if det.zone_name:
                label += f" ▶{det.zone_name}"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ly = max(y1 - 4, lh + 4)
            cv2.rectangle(frame, (x1, ly - lh - 4), (x1 + lw + 4, ly), color, -1)
            cv2.putText(frame, label, (x1 + 2, ly - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

        cv2.putText(frame, f"YOLO | vehicles:{len(detections)}", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
        return frame

    def get_info(self) -> dict:
        return {
            "enabled": self.enabled,
            "model_path": self.model_path,
            "is_ready": self.is_ready,
            "load_error": self._load_error,
            "conf": self.conf,
            "iou": self.iou,
            "imgsz": self.imgsz,
            "device": self.device,
            "vehicle_classes": list(self.vehicle_classes),
            "min_zone_overlap": self.min_zone_overlap,
        }
