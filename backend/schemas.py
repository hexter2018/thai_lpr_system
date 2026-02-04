# schemas.py
from __future__ import annotations

from typing import Optional, Any, Dict
from pydantic import BaseModel, Field

class RecognizeResponse(BaseModel):
    log_id: int
    license_text: str
    province: str
    confidence: float
    status: str
    master_id: Optional[int] = None
    original_image_path: str
    cropped_plate_image_path: str
    debug: Optional[Dict[str, Any]] = None

class VerifyRequest(BaseModel):
    corrected_license: str = Field(..., min_length=1)
    corrected_province: str = Field(..., min_length=1)
    is_correct: bool

class StatsResponse(BaseModel):
    total_scanned: int
    alpr_count: int
    mlpr_count: int
    pending_count: int
    accuracy_percent: float
    accuracy_verified_percent: float
