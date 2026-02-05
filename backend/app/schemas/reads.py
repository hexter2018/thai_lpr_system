from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal

class ReadOut(BaseModel):
    id: int
    plate_text: str
    plate_text_norm: str
    province: str
    confidence: float
    status: str
    created_at: datetime
    crop_url: str
    original_url: str

class VerifyIn(BaseModel):
    action: Literal["confirm", "correct"]
    corrected_text: Optional[str] = None
    corrected_province: Optional[str] = None
    note: Optional[str] = None
    user: Optional[str] = "reviewer"
