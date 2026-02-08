from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.db import models
from app.schemas.master import MasterOut, MasterUpsertIn, MasterCropOut
from app.services.storage import make_image_url

router = APIRouter()

@router.get("/master", response_model=list[MasterOut])
def search_master(q: str = "", limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(models.MasterPlate)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(models.MasterPlate.plate_text_norm.ilike(like))
    query = query.order_by(desc(models.MasterPlate.last_seen)).limit(limit)
    return [MasterOut(**m.__dict__) for m in query.all()]

@router.get("/master/{master_id}/crops", response_model=list[MasterCropOut])
def get_master_crops(
    master_id: int,
    limit: int = Query(5, le=20),
    db: Session = Depends(get_db)
):
    """Get crop images associated with a master plate record"""
    master = db.query(models.MasterPlate).filter(models.MasterPlate.id == master_id).first()
    if not master:
        raise HTTPException(status_code=404, detail="master not found")
    
    # Find plate_reads with matching plate_text_norm
    reads = db.query(models.PlateRead).filter(
        models.PlateRead.plate_text_norm == master.plate_text_norm,
        models.PlateRead.status == models.ReadStatus.VERIFIED
    ).order_by(
        desc(models.PlateRead.confidence)
    ).limit(limit).all()
    
    crops = []
    for read in reads:
        if read.detection and read.detection.crop_path:
            crops.append(MasterCropOut(
                read_id=read.id,
                crop_url=make_image_url(read.detection.crop_path),
                confidence=read.confidence,
                created_at=read.created_at
            ))
    
    return crops

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


@router.delete("/master/{master_id}")
def delete_master(master_id: int, db: Session = Depends(get_db)):
    m = db.query(models.MasterPlate).filter(models.MasterPlate.id == master_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="master record not found")
    db.delete(m)
    db.commit()
    return {"ok": True}
