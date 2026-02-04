# backend/api_queue.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db import get_session
from models import ScanLog, ScanStatus

router = APIRouter()

@router.get("/api/queue/pending")
async def get_pending_queue(limit: int = 50, session: AsyncSession = Depends(get_session)):
    q = select(ScanLog).where(ScanLog.status == ScanStatus.PENDING).order_by(ScanLog.created_at.desc()).limit(limit)
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "original_image_path": r.original_image_path,
            "cropped_plate_image_path": r.cropped_plate_image_path,
            "detected_text": r.detected_text,
            "detected_province": r.detected_province,
            "confidence_score": r.confidence_score,
            "status": r.status.value,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
