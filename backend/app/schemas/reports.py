from pydantic import BaseModel
from typing import List, Dict, Any

class ProvinceCount(BaseModel):
    province: str
    count: int

class DateRange(BaseModel):
    start: str
    end: str

class ReportStats(BaseModel):
    total_reads: int
    verified_reads: int
    alpr_total: int
    mlpr_total: int
    accuracy: float
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    top_provinces: List[Dict[str, Any]]
    date_range: Dict[str, str]

class ActivityLog(BaseModel):
    id: int
    plate_text: str
    province: str
    confidence: float
    status: str
    created_at: str
    camera_id: str
    source: str
    crop_url: str

class AccuracyMetrics(BaseModel):
    date: str
    alpr: int
    mlpr: int
    total: int
    accuracy: float