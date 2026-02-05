from datetime import datetime
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.reads import VerifyIn
from app.services.master import upsert_master_from_read, store_feedback_if_mlpr
from app.services.textnorm import normalize_plate_text

def verify_read(db: Session, read: models.PlateRead, payload: VerifyIn):
    # ensure verification job exists
    job = db.query(models.VerificationJob).filter(models.VerificationJob.read_id == read.id).first()
    if not job:
        job = models.VerificationJob(read_id=read.id)
        db.add(job)
        db.flush()

    if payload.action == "confirm":
        job.result_type = models.VerifyResultType.ALPR
        job.corrected_text = None
        job.corrected_province = None
        read.status = models.ReadStatus.VERIFIED
        # After human confirm, treat as true ALPR and update master
        upsert_master_from_read(db, read, force=True)
    else:
        # corrected
        corr_text = payload.corrected_text or ""
        corr_prov = payload.corrected_province or ""
        job.result_type = models.VerifyResultType.MLPR
        job.corrected_text = corr_text
        job.corrected_province = corr_prov
        read.plate_text = corr_text
        read.plate_text_norm = normalize_plate_text(corr_text)
        read.province = corr_prov
        read.status = models.ReadStatus.VERIFIED

        upsert_master_from_read(db, read, force=True)
        store_feedback_if_mlpr(db, read)

    job.note = payload.note
    job.assigned_to = payload.user
    job.verified_at = datetime.utcnow()
    db.commit()
