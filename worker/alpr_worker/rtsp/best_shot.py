# worker/alpr_worker/rtsp/best_shot.py
import os
import time
import cv2
import numpy as np
import re

def norm_plate_text(s: str) -> str:
    if not s:
        return ""
    s = s.strip().upper()
    s = s.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
    s = re.sub(r"[\s\-\.]", "", s)
    return s

def lap_var(bgr: np.ndarray) -> float:
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(g, cv2.CV_64F).var()

class BestShotSelector:
    """
    เลือก 1 รูปที่ดีที่สุดต่อ 1 ป้าย (1 คัน) ภายใน window เวลา
    """
    def __init__(self):
        self.window_sec = float(os.getenv("RTSP_BESTSHOT_WINDOW_SEC", "2.5"))
        self.gap_sec = float(os.getenv("RTSP_BESTSHOT_GAP_SEC", "1.0"))
        self.min_ocr_conf = float(os.getenv("RTSP_BESTSHOT_MIN_OCR_CONF", "0.70"))
        self.fast_conf = float(os.getenv("RTSP_BESTSHOT_FAST_CONF", "0.95"))

        self.reset()

    def reset(self):
        self.key = None
        self.t0 = 0.0
        self.t_last = 0.0
        self.best = None  # dict(score=..., tmp_path=..., meta=...)

    def score(self, ocr_conf: float, det_conf: float, plate_crop_bgr: np.ndarray, frame_q: float, plate_area_ratio: float) -> float:
        sharp = lap_var(plate_crop_bgr)
        sharp_norm = min(1.0, sharp / 300.0)  # ปรับตามหน้างานได้
        q_norm = min(1.0, frame_q / 100.0)
        area_norm = min(1.0, plate_area_ratio / 0.08)

        # น้ำหนักเน้น OCR ก่อน -> ลดอ่านผิด
        return (0.55 * ocr_conf) + (0.15 * det_conf) + (0.15 * sharp_norm) + (0.10 * q_norm) + (0.05 * area_norm)

    def update(self, now: float, key: str, cand: dict):
        """
        คืนค่า: finalized_candidate หรือ None
        """
        if not key or cand.get("ocr_conf", 0.0) < self.min_ocr_conf:
            return None

        if self.key is None:
            self.key = key
            self.t0 = now
            self.t_last = now
            self.best = cand
            if cand.get("fast", False):
                out = self.best
                self.reset()
                return out
            return None

        # คันเดิม
        if key == self.key:
            self.t_last = now
            if self.best is None or cand["score"] > self.best["score"]:
                self.best = cand

            if cand.get("fast", False):
                out = self.best
                self.reset()
                return out

            if (now - self.t0) >= self.window_sec:
                out = self.best
                self.reset()
                return out
            return None

        # เปลี่ยนคัน (ป้ายใหม่) -> finalize คันเก่า แล้วเริ่มคันใหม่
        out = self.best
        self.reset()
        self.key = key
        self.t0 = now
        self.t_last = now
        self.best = cand
        if cand.get("fast", False):
            out2 = self.best
            self.reset()
            return out2
        return out

    def flush_if_gap(self, now: float):
        if self.key and (now - self.t_last) >= self.gap_sec:
            out = self.best
            self.reset()
            return out
        return None
