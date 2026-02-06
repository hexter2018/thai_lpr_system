from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from app.db.session import get_db
from app.db import models
from app.schemas.reads import ReadOut, VerifyIn
from app.services.storage import make_image_url
from app.services.verification import verify_read

router = APIRouter()

@router.get("/reads/pending", response_model=list[ReadOut])
def list_pending(limit: int = 100, db: Session = Depends(get_db)):
    q = (
        db.query(models.PlateRead)
        .join(models.Detection, models.PlateRead.detection_id == models.Detection.id)
        .join(models.Capture, models.Detection.capture_id == models.Capture.id)
        .filter(models.PlateRead.status == models.ReadStatus.PENDING)
        .order_by(desc(models.PlateRead.created_at))
        .limit(limit)
    )
    out = []
    for r in q.all():
        det = r.detection
        cap = det.capture
        out.append(ReadOut(
            id=r.id,
            plate_text=r.plate_text,
            plate_text_norm=r.plate_text_norm,
            province=r.province,
            confidence=r.confidence,
            status=r.status.value,
            created_at=r.created_at,
            crop_url=make_image_url(det.crop_path),
            original_url=make_image_url(cap.original_path),
        ))
    return out

@router.post("/reads/{read_id}/verify")
def verify(read_id: int, payload: VerifyIn, db: Session = Depends(get_db)):
    r = db.query(models.PlateRead).filter(models.PlateRead.id == read_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="read not found")
    verify_read(db, r, payload)
    return {"ok": True}


@router.delete("/reads/{read_id}")
def delete_read(read_id: int, db: Session = Depends(get_db)):
    r = db.query(models.PlateRead).filter(models.PlateRead.id == read_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="read not found")
    if r.verification:
        db.delete(r.verification)
    db.delete(r)
    db.commit()
    return {"ok": True}
