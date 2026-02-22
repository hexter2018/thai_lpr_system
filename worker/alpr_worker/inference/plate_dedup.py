"""
plate_dedup.py — Plate-Level Deduplication
============================================

Drop duplicate OCR outputs for the same plate text and camera within cooldown.
"""

import json
import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """Plate dedup check result."""
    is_duplicate: bool
    action: str              # "new", "skip"
    existing_capture_id: int
    existing_confidence: float
    reason: str


class PlateDedup:
    """Redis-based plate text deduplication scoped by camera + plate text."""

    def __init__(self, redis_client=None):
        self.enabled = os.getenv("PLATE_DEDUP_ENABLED", "true").lower() == "true"
        self.cooldown_sec = int(os.getenv("PLATE_DEDUP_COOLDOWN_SEC", "180"))
        self.min_confidence = float(os.getenv("PLATE_DEDUP_MIN_CONFIDENCE", "0.30"))
        self.camera_scope = os.getenv("PLATE_DEDUP_CAMERA_SCOPE", "true").lower() == "true"
        self.redis = redis_client

        log.info(
            "PlateDedup: enabled=%s cooldown=%ds min_conf=%.2f camera_scope=%s",
            self.enabled, self.cooldown_sec, self.min_confidence, self.camera_scope,
        )

    def _key(self, plate_text_norm: str, camera_id: str = "") -> str:
        if self.camera_scope and camera_id:
            return f"plate_dedup:{camera_id}:{plate_text_norm}"
        return f"plate_dedup:{plate_text_norm}"

    def check(
        self,
        plate_text_norm: str,
        confidence: float,
        capture_id: int,
        camera_id: str = "",
    ) -> DedupResult:
        if not self.enabled:
            return DedupResult(False, "new", 0, 0.0, "dedup_disabled")

        if not plate_text_norm or len(plate_text_norm) < 3:
            return DedupResult(False, "new", 0, 0.0, "plate_too_short")

        if confidence < self.min_confidence:
            return DedupResult(False, "new", 0, 0.0, "confidence_below_min")

        if self.redis is None:
            return DedupResult(False, "new", 0, 0.0, "no_redis")

        key = self._key(plate_text_norm, camera_id)

        try:
            existing_raw = self.redis.get(key)
        except Exception as e:
            log.warning("PlateDedup Redis error: %s", e)
            return DedupResult(False, "new", 0, 0.0, f"redis_error:{e}")

        if existing_raw is not None:
            existing_capture_id = 0
            existing_confidence = 0.0
            try:
                existing = json.loads(existing_raw)
                existing_capture_id = int(existing.get("capture_id", 0))
                existing_confidence = float(existing.get("confidence", 0.0))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            log.info(
                "PlateDedup: SKIP duplicate plate=%s camera=%s existing_cap=%d",
                plate_text_norm,
                camera_id,
                existing_capture_id,
            )
            return DedupResult(
                is_duplicate=True,
                action="skip",
                existing_capture_id=existing_capture_id,
                existing_confidence=existing_confidence,
                reason="duplicate_within_cooldown",
            )

        self._set(key, capture_id, confidence)
        return DedupResult(False, "new", 0, 0.0, "first_seen")

    def _set(self, key: str, capture_id: int, confidence: float):
        try:
            data = json.dumps({
                "capture_id": capture_id,
                "confidence": round(confidence, 4),
                "timestamp": time.time(),
            })
            self.redis.setex(key, self.cooldown_sec, data)
        except Exception as e:
            log.warning("PlateDedup Redis set error: %s", e)

    def clear(self, plate_text_norm: str, camera_id: str = ""):
        if self.redis is None:
            return
        key = self._key(plate_text_norm, camera_id)
        try:
            self.redis.delete(key)
        except Exception as e:
            log.warning("PlateDedup Redis delete error: %s", e)

    def get_stats(self, camera_id: str = "") -> dict:
        if self.redis is None:
            return {"active_plates": 0}
        try:
            pattern = f"plate_dedup:{camera_id}:*" if camera_id else "plate_dedup:*"
            keys = list(self.redis.scan_iter(match=pattern, count=100))
            return {"active_plates": len(keys), "pattern": pattern}
        except Exception as e:
            return {"active_plates": -1, "error": str(e)}
