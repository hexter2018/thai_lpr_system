"""
plate_dedup.py — Plate-Level Deduplication
============================================

ป้องกันทะเบียนเดียวกันถูก process ซ้ำหลายรอบ

ปัญหา:
- รถ 1 คันผ่านหน้ากล้อง → BestShot เลือก 1 frame/event
- แต่ถ้ารถจอดนาน/เคลื่อนที่ช้า → อาจเกิดหลาย events
- Frame dedup (perceptual hash) จับได้แค่ภาพที่เหมือนกันจริงๆ
- รถขยับนิดเดียว → hash ต่าง → ไม่ถือเป็น duplicate
- ผลลัพธ์: ป้ายเดียวกันซ้ำ 3-5 รายการใน verification queue

วิธีแก้:
- หลัง OCR อ่านได้ plate_text_norm → เช็คกับ Redis
- ถ้าเคยเห็นภายใน COOLDOWN_SEC → skip (return dedup result)
- ถ้าไม่เคยเห็น → set key ใน Redis พร้อม TTL
- เลือกเก็บ record ที่ confidence สูงที่สุด

ENV:
  PLATE_DEDUP_ENABLED=true
  PLATE_DEDUP_COOLDOWN_SEC=60       วินาทีที่ถือว่าป้ายเดียวกัน
  PLATE_DEDUP_MIN_CONFIDENCE=0.30   ป้ายที่ conf ต่ำกว่านี้ไม่เข้า dedup (ข้อมูลไม่น่าเชื่อถือ)
  PLATE_DEDUP_CAMERA_SCOPE=true     dedup แยกตาม camera_id (true) หรือรวมทุกกล้อง (false)
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """ผลการตรวจสอบ dedup"""
    is_duplicate: bool
    action: str              # "new", "skip", "update"
    existing_capture_id: int  # capture_id ที่เคยเห็น (0 ถ้าเป็น new)
    existing_confidence: float
    reason: str


class PlateDedup:
    """
    Redis-based plate-level deduplication

    Usage:
        dedup = PlateDedup(redis_client)

        # หลัง OCR:
        result = dedup.check(
            plate_text_norm="1ฆข4048",
            confidence=0.72,
            capture_id=123,
            camera_id="cam1",
        )
        if result.is_duplicate:
            if result.action == "skip":
                # ข้ามเลย — record เดิม conf สูงกว่า
                pass
            elif result.action == "update":
                # อัปเดต record เดิมด้วย conf ใหม่ที่สูงกว่า
                update_existing(result.existing_capture_id, ...)
        else:
            # record ใหม่ — insert ปกติ
            insert_plate_read(...)
    """

    def __init__(self, redis_client=None):
        self.enabled = os.getenv("PLATE_DEDUP_ENABLED", "true").lower() == "true"
        self.cooldown_sec = int(os.getenv("PLATE_DEDUP_COOLDOWN_SEC", "60"))
        self.min_confidence = float(os.getenv("PLATE_DEDUP_MIN_CONFIDENCE", "0.30"))
        self.camera_scope = os.getenv("PLATE_DEDUP_CAMERA_SCOPE", "true").lower() == "true"

        self.redis = redis_client

        log.info(
            "PlateDedup: enabled=%s cooldown=%ds min_conf=%.2f camera_scope=%s",
            self.enabled, self.cooldown_sec, self.min_confidence, self.camera_scope,
        )

    def _key(self, plate_text_norm: str, camera_id: str = "") -> str:
        """สร้าง Redis key สำหรับ dedup"""
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
        """
        ตรวจว่าทะเบียนนี้เคยเห็นภายใน cooldown period หรือไม่

        Returns:
            DedupResult
        """
        if not self.enabled:
            return DedupResult(
                is_duplicate=False,
                action="new",
                existing_capture_id=0,
                existing_confidence=0.0,
                reason="dedup_disabled",
            )

        if not plate_text_norm or len(plate_text_norm) < 3:
            return DedupResult(
                is_duplicate=False,
                action="new",
                existing_capture_id=0,
                existing_confidence=0.0,
                reason="plate_too_short",
            )

        if confidence < self.min_confidence:
            return DedupResult(
                is_duplicate=False,
                action="new",
                existing_capture_id=0,
                existing_confidence=0.0,
                reason="confidence_below_min",
            )

        if self.redis is None:
            return DedupResult(
                is_duplicate=False,
                action="new",
                existing_capture_id=0,
                existing_confidence=0.0,
                reason="no_redis",
            )

        key = self._key(plate_text_norm, camera_id)

        try:
            existing_raw = self.redis.get(key)
        except Exception as e:
            log.warning("PlateDedup Redis error: %s", e)
            return DedupResult(
                is_duplicate=False,
                action="new",
                existing_capture_id=0,
                existing_confidence=0.0,
                reason=f"redis_error:{e}",
            )

        if existing_raw is not None:
            # เคยเห็นป้ายนี้ภายใน cooldown
            try:
                existing = json.loads(existing_raw)
                existing_capture_id = int(existing.get("capture_id", 0))
                existing_confidence = float(existing.get("confidence", 0.0))
                existing_time = float(existing.get("timestamp", 0.0))
            except (json.JSONDecodeError, TypeError, ValueError):
                existing_capture_id = 0
                existing_confidence = 0.0
                existing_time = 0.0

            if confidence > existing_confidence:
                # record ใหม่ conf สูงกว่า → อัปเดต
                self._set(key, capture_id, confidence)
                log.info(
                    "PlateDedup: UPDATE %s (old_conf=%.2f → new_conf=%.2f, old_cap=%d → new_cap=%d)",
                    plate_text_norm, existing_confidence, confidence,
                    existing_capture_id, capture_id,
                )
                return DedupResult(
                    is_duplicate=True,
                    action="update",
                    existing_capture_id=existing_capture_id,
                    existing_confidence=existing_confidence,
                    reason="higher_confidence",
                )
            else:
                # record เดิม conf สูงกว่า → skip
                log.info(
                    "PlateDedup: SKIP %s (existing_conf=%.2f ≥ new_conf=%.2f, cap=%d)",
                    plate_text_norm, existing_confidence, confidence, existing_capture_id,
                )
                return DedupResult(
                    is_duplicate=True,
                    action="skip",
                    existing_capture_id=existing_capture_id,
                    existing_confidence=existing_confidence,
                    reason="existing_higher_confidence",
                )

        # ไม่เคยเห็น → new record
        self._set(key, capture_id, confidence)
        return DedupResult(
            is_duplicate=False,
            action="new",
            existing_capture_id=0,
            existing_confidence=0.0,
            reason="first_seen",
        )

    def _set(self, key: str, capture_id: int, confidence: float):
        """Set plate record ใน Redis พร้อม TTL"""
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
        """ลบ dedup record (ใช้เมื่อ operator แก้ไขทะเบียน)"""
        if self.redis is None:
            return
        key = self._key(plate_text_norm, camera_id)
        try:
            self.redis.delete(key)
        except Exception as e:
            log.warning("PlateDedup Redis delete error: %s", e)

    def get_stats(self, camera_id: str = "") -> dict:
        """ดูจำนวน plate keys ที่ active อยู่"""
        if self.redis is None:
            return {"active_plates": 0}
        try:
            pattern = f"plate_dedup:{camera_id}:*" if camera_id else "plate_dedup:*"
            keys = list(self.redis.scan_iter(match=pattern, count=100))
            return {"active_plates": len(keys), "pattern": pattern}
        except Exception as e:
            return {"active_plates": -1, "error": str(e)}