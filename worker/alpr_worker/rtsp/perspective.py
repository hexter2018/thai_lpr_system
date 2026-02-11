import logging
import os
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class PerspectiveFix:
    """
    Perspective correction for skewed license plates.

    ⚠️ SAFE: returns original image on ANY failure — never crashes pipeline.
    """

    def __init__(self):
        self.enabled = os.getenv("PERSPECTIVE_FIX_ENABLED", "true").lower() == "true"
        self.min_area = int(os.getenv("PERSPECTIVE_FIX_MIN_AREA", "500"))
        self.debug = os.getenv("PERSPECTIVE_FIX_DEBUG", "false").lower() == "true"
        self.output_width = 400
        self.output_height = 200
        log.info(
            "PerspectiveFix: enabled=%s min_area=%d output=%dx%d",
            self.enabled, self.min_area, self.output_width, self.output_height,
        )

    def fix(self, image: np.ndarray) -> np.ndarray:
        """Apply perspective correction. NEVER raises."""
        if not self.enabled:
            return image
        if image is None or image.size == 0:
            return image
        try:
            corners = self._find_plate_corners(image)
            if corners is None:
                if self.debug:
                    log.debug("PerspectiveFix: no corners found — using original")
                return image

            ordered = self._order_points(corners)

            # Skip if quad covers >92% of crop (nothing to correct)
            h, w = image.shape[:2]
            quad_area = cv2.contourArea(ordered)
            if quad_area > h * w * 0.92:
                if self.debug:
                    log.debug("PerspectiveFix: quad ≈ full crop — skip")
                return image

            corrected = self._warp(image, ordered)
            if corrected is None or corrected.size == 0:
                return image
            return corrected
        except Exception as e:
            log.warning("PerspectiveFix error (using original): %s", e)
            return image

    def _find_plate_corners(self, image: np.ndarray) -> Optional[np.ndarray]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, blockSize=31, C=5,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < self.min_area:
            return None
        eps = 0.02 * cv2.arcLength(largest, True)
        approx = cv2.approxPolyDP(largest, eps, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
        rect = cv2.minAreaRect(largest)
        return cv2.boxPoints(rect).astype(np.float32)

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        """TL, TR, BR, BL — robust sum/diff method."""
        s = pts.sum(axis=1)
        d = np.diff(pts, axis=1).ravel()
        tl = pts[np.argmin(s)]
        br = pts[np.argmax(s)]
        tr = pts[np.argmin(d)]
        bl = pts[np.argmax(d)]
        return np.array([tl, tr, br, bl], dtype=np.float32)

    def _warp(self, image: np.ndarray, corners: np.ndarray) -> Optional[np.ndarray]:
        dst = np.array([
            [0, 0],
            [self.output_width - 1, 0],
            [self.output_width - 1, self.output_height - 1],
            [0, self.output_height - 1],
        ], dtype=np.float32)
        M = cv2.getPerspectiveTransform(corners, dst)
        return cv2.warpPerspective(
            image, M, (self.output_width, self.output_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )