"""
roi_reader.py — Safe ROI Reader for RTSP Producer
====================================================

อ่านค่า ROI จาก Redis (ที่ Dashboard เขียน) แบบปลอดภัย

Safety Guarantees:
  1. Redis ตาย     → fallback ไป ENV เดิม (ไม่ crash)
  2. Redis มีค่าผิด → ไม่ใช้ fallback ไป ENV เดิม
  3. ROI แคบเกิน   → ใช้ค่า default แทน
  4. Cache 2 วินาที → ไม่ query Redis ทุก frame
  5. Feature flag   → RTSP_ROI_REDIS_ENABLED=false ปิดได้ทันที

Usage ใน frame_producer.py:
  roi_reader = ROIReader(redis_client, camera_id="PCN_Lane4")

  while True:
      frame = capture_frame()
      roi = roi_reader.get_roi()  # safe — never throws
      h, w = frame.shape[:2]
      x1, y1 = int(roi["x1"] * w), int(roi["y1"] * h)
      x2, y2 = int(roi["x2"] * w), int(roi["y2"] * h)
      cropped = frame[y1:y2, x1:x2]
"""

import json
import logging
import os
import time
from typing import Dict, Optional

log = logging.getLogger(__name__)


class ROIReader:
    """
    Safe Redis-based ROI reader with multi-layer fallback

    Priority:
      1. Redis (from Dashboard)     — ถ้า enabled + Redis healthy + ค่า valid
      2. ENV (docker-compose)       — ถ้า Redis ไม่มี/ผิด/ตาย
      3. Hardcoded default          — ถ้า ENV ก็ไม่มี (full frame)
    """

    # Hardcoded default — ใช้ทั้ง frame (ไม่ crop เลย)
    FULL_FRAME = {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}

    # Minimum ROI area (5% of frame) — ป้องกัน ROI แคบเกินจนจับอะไรไม่ได้
    MIN_AREA = 0.05

    # Maximum ROI area sanity check
    MAX_AREA = 1.0

    def __init__(self, redis_client=None, camera_id: str = ""):
        self.camera_id = camera_id
        self.redis = redis_client

        # Feature flag — ปิดได้ทันที
        self.redis_enabled = os.getenv(
            "RTSP_ROI_REDIS_ENABLED", "false"
        ).lower() == "true"

        self.key_prefix = os.getenv(
            "RTSP_ROI_REDIS_KEY_PREFIX", "alpr:roi"
        )

        # ENV fallback — อ่านค่าจาก docker-compose
        self._env_roi = self._read_env_roi()

        # Cache — ไม่ query Redis ทุก frame
        self._cache: Optional[Dict] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 2.0  # seconds

        # Health tracking
        self._redis_failures: int = 0
        self._redis_max_failures: int = 5  # หลัง 5 failures → ปิด Redis อ่าน
        self._redis_recovery_time: float = 0.0
        self._redis_recovery_interval: float = 30.0  # retry ทุก 30 วินาที

        # Stats
        self._source = "init"
        self._total_reads = 0
        self._redis_reads = 0
        self._env_reads = 0
        self._default_reads = 0

        log.info(
            "ROIReader init: camera=%s redis_enabled=%s env_roi=%s",
            camera_id, self.redis_enabled, self._env_roi,
        )

    def _read_env_roi(self) -> Dict:
        """อ่าน ROI จาก ENV (docker-compose) — layer 2"""
        try:
            roi = {
                "x1": float(os.getenv("RTSP_ROI_X1", "0.0")),
                "y1": float(os.getenv("RTSP_ROI_Y1", "0.0")),
                "x2": float(os.getenv("RTSP_ROI_X2", "1.0")),
                "y2": float(os.getenv("RTSP_ROI_Y2", "1.0")),
            }
            if self._validate_roi(roi):
                return roi
        except (ValueError, TypeError) as e:
            log.warning("ROIReader: invalid ENV roi values: %s", e)

        return self.FULL_FRAME.copy()

    def _validate_roi(self, roi: Dict) -> bool:
        """
        ตรวจสอบว่า ROI ถูกต้อง

        Rules:
          - ทุกค่าต้องอยู่ใน [0.0, 1.0]
          - x1 < x2, y1 < y2
          - area >= MIN_AREA (5%)
          - area <= MAX_AREA (100%)
        """
        try:
            x1 = float(roi.get("x1", -1))
            y1 = float(roi.get("y1", -1))
            x2 = float(roi.get("x2", -1))
            y2 = float(roi.get("y2", -1))
        except (ValueError, TypeError):
            return False

        # Range check
        if not (0.0 <= x1 < x2 <= 1.0):
            return False
        if not (0.0 <= y1 < y2 <= 1.0):
            return False

        # Area check
        area = (x2 - x1) * (y2 - y1)
        if area < self.MIN_AREA or area > self.MAX_AREA:
            return False

        return True

    def _is_redis_healthy(self) -> bool:
        """เช็คว่า Redis ยังใช้ได้"""
        if not self.redis_enabled:
            return False
        if self.redis is None:
            return False

        # หลัง N failures → หยุดใช้ Redis ชั่วคราว
        if self._redis_failures >= self._redis_max_failures:
            now = time.time()
            if now < self._redis_recovery_time:
                return False
            # ลอง recover
            log.info(
                "ROIReader: attempting Redis recovery (failures=%d)",
                self._redis_failures,
            )
            self._redis_failures = 0  # reset เพื่อลองใหม่

        return True

    def _read_redis_roi(self) -> Optional[Dict]:
        """
        อ่าน ROI จาก Redis — layer 1

        Returns:
            dict if valid, None if unavailable/invalid
        """
        if not self._is_redis_healthy():
            return None

        key = f"{self.key_prefix}:{self.camera_id}"

        try:
            raw = self.redis.get(key)
            if raw is None:
                return None

            # Decode if bytes
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            data = json.loads(raw)

            roi = {
                "x1": float(data.get("x1", -1)),
                "y1": float(data.get("y1", -1)),
                "x2": float(data.get("x2", -1)),
                "y2": float(data.get("y2", -1)),
            }

            if self._validate_roi(roi):
                # Success — reset failure counter
                self._redis_failures = 0
                return roi
            else:
                log.warning(
                    "ROIReader: invalid ROI from Redis key=%s data=%s",
                    key, data,
                )
                return None

        except json.JSONDecodeError as e:
            log.warning("ROIReader: Redis JSON decode error: %s", e)
            self._redis_failures += 1
            return None

        except Exception as e:
            # Redis connection error — increment failure counter
            self._redis_failures += 1
            self._redis_recovery_time = (
                time.time() + self._redis_recovery_interval
            )
            if self._redis_failures <= 3:
                # Log first few failures only
                log.warning(
                    "ROIReader: Redis error (failure #%d): %s",
                    self._redis_failures, e,
                )
            return None

    def get_roi(self) -> Dict:
        """
        อ่าน ROI — safe, never throws

        ลำดับ:
          1. Cache (ถ้ายังไม่หมดอายุ)
          2. Redis (ถ้า enabled + healthy + valid)
          3. ENV (docker-compose)
          4. Hardcoded default (full frame)

        Returns:
            {"x1": float, "y1": float, "x2": float, "y2": float}
        """
        self._total_reads += 1

        # Check cache
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        # Try Redis
        redis_roi = self._read_redis_roi()
        if redis_roi is not None:
            self._cache = redis_roi
            self._cache_time = now
            self._source = "redis"
            self._redis_reads += 1
            return redis_roi

        # Fallback to ENV
        if self._validate_roi(self._env_roi):
            self._cache = self._env_roi
            self._cache_time = now
            self._source = "env"
            self._env_reads += 1
            return self._env_roi

        # Last resort — full frame
        self._cache = self.FULL_FRAME.copy()
        self._cache_time = now
        self._source = "default"
        self._default_reads += 1
        return self._cache

    def get_pixel_roi(self, frame_width: int, frame_height: int) -> Dict:
        """
        ค่า ROI เป็น pixel coordinates — พร้อมใช้ crop เลย

        Returns:
            {"x1": int, "y1": int, "x2": int, "y2": int}
        """
        roi = self.get_roi()
        return {
            "x1": int(roi["x1"] * frame_width),
            "y1": int(roi["y1"] * frame_height),
            "x2": int(roi["x2"] * frame_width),
            "y2": int(roi["y2"] * frame_height),
        }

    def invalidate_cache(self):
        """บังคับอ่านค่าใหม่ (ใช้หลังรับ pub/sub event)"""
        self._cache = None
        self._cache_time = 0.0

    def get_source(self) -> str:
        """บอกว่าค่าปัจจุบันมาจากไหน: redis / env / default"""
        return self._source

    def get_stats(self) -> Dict:
        """สถิติสำหรับ monitoring"""
        return {
            "camera_id": self.camera_id,
            "redis_enabled": self.redis_enabled,
            "source": self._source,
            "total_reads": self._total_reads,
            "redis_reads": self._redis_reads,
            "env_reads": self._env_reads,
            "default_reads": self._default_reads,
            "redis_failures": self._redis_failures,
            "current_roi": self._cache,
        }

    def health_check(self) -> Dict:
        """Health check สำหรับ monitoring endpoint"""
        healthy = True
        issues = []

        if self.redis_enabled and self.redis is None:
            healthy = False
            issues.append("redis_client_is_none")

        if self._redis_failures >= self._redis_max_failures:
            issues.append(f"redis_circuit_open (failures={self._redis_failures})")

        if self._source == "default":
            issues.append("using_hardcoded_default_roi")

        return {
            "healthy": healthy,
            "source": self._source,
            "redis_failures": self._redis_failures,
            "issues": issues,
        }