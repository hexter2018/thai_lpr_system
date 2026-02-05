from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.db import models
from app.schemas.dashboard import KPI

router = APIRouter()

@router.get("/dashboard/kpi", response_model=KPI)
def dashboard_kpi(db: Session = Depends(get_db)):
    total_reads = db.query(func.count(models.PlateRead.id)).scalar() or 0
    pending = db.query(func.count(models.PlateRead.id)).filter(models.PlateRead.status == models.ReadStatus.PENDING).scalar() or 0
    verified = db.query(func.count(models.PlateRead.id)).filter(models.PlateRead.status == models.ReadStatus.VERIFIED).scalar() or 0

    master_total = db.query(func.count(models.MasterPlate.id)).scalar() or 0

    alpr_total = db.query(func.count(models.VerificationJob.id)).filter(models.VerificationJob.result_type == models.VerifyResultType.ALPR).scalar() or 0
    mlpr_total = db.query(func.count(models.VerificationJob.id)).filter(models.VerificationJob.result_type == models.VerifyResultType.MLPR).scalar() or 0

    # auto_master heuristic: reads with confidence >= 0.95 and verified OR inserted into master
    auto_master = db.query(func.count(models.PlateRead.id)).filter(models.PlateRead.confidence >= 0.95).scalar() or 0

    return KPI(
        total_reads=total_reads,
        pending=pending,
        verified=verified,
        auto_master=auto_master,
        master_total=master_total,
        mlpr_total=mlpr_total,
        alpr_total=alpr_total,
    )
