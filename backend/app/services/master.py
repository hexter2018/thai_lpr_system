from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import models

def upsert_master_from_read(db: Session, read: models.PlateRead, force: bool = False):
    norm = read.plate_text_norm
    if not norm:
        return

    m = db.query(models.MasterPlate).filter(models.MasterPlate.plate_text_norm == norm).first()
    if not m:
        m = models.MasterPlate(
            plate_text_norm=norm,
            display_text=read.plate_text or norm,
            province=read.province or "",
            confidence=float(read.confidence or 0.0),
            last_seen=datetime.utcnow(),
            count_seen=1,
            editable=True,
        )
        db.add(m)
    else:
        m.last_seen = datetime.utcnow()
        m.count_seen = (m.count_seen or 0) + 1
        # keep best confidence
        if (read.confidence or 0.0) > (m.confidence or 0.0):
            m.confidence = float(read.confidence)
        # update province/display if empty
        if not m.province and read.province:
            m.province = read.province
        if not m.display_text and read.plate_text:
            m.display_text = read.plate_text
    db.flush()

def store_feedback_if_mlpr(db: Session, read: models.PlateRead):
    # store a training sample when human corrected
    det = read.detection
    if not det:
        return
    sample = models.FeedbackSample(
        crop_path=det.crop_path,
        corrected_text=read.plate_text,
        corrected_province=read.province,
        reason="MLPR",
        used_in_train=False,
    )
    db.add(sample)
    db.flush()
