from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.db import models
from app.schemas.master import MasterOut, MasterUpsertIn

router = APIRouter()

@router.get("/master", response_model=list[MasterOut])
def search_master(q: str = "", limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(models.MasterPlate)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(models.MasterPlate.plate_text_norm.ilike(like))
    query = query.order_by(desc(models.MasterPlate.last_seen)).limit(limit)
    return [MasterOut(**m.__dict__) for m in query.all()]

@router.post("/master", response_model=MasterOut)
def upsert_master(payload: MasterUpsertIn, db: Session = Depends(get_db)):
    m = db.query(models.MasterPlate).filter(models.MasterPlate.plate_text_norm == payload.plate_text_norm).first()
    if m:
        if not m.editable:
            raise HTTPException(status_code=400, detail="master record not editable")
        m.display_text = payload.display_text
        m.province = payload.province
        m.confidence = payload.confidence
        m.editable = payload.editable
    else:
        m = models.MasterPlate(
            plate_text_norm=payload.plate_text_norm,
            display_text=payload.display_text,
            province=payload.province,
            confidence=payload.confidence,
            editable=payload.editable,
        )
        db.add(m)
    db.commit()
    db.refresh(m)
    return MasterOut(**m.__dict__)
