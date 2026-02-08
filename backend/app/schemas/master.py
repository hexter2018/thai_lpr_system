from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class MasterOut(BaseModel):
    id: int
    plate_text_norm: str
    display_text: str
    province: str
    confidence: float
    last_seen: datetime
    count_seen: int
    editable: bool

class MasterCropOut(BaseModel):
    read_id: int
    crop_url: str
    confidence: float
    created_at: datetime

class MasterUpsertIn(BaseModel):
    plate_text_norm: str
    display_text: str
    province: str
    confidence: float = 1.0
    editable: bool = True
