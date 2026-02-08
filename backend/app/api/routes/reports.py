from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from typing import Optional
import csv
import io

from app.db.session import get_db
from app.db import models
from app.schemas.reports import ReportStats, ActivityLog, AccuracyMetrics
from app.services.storage import make_image_url

router = APIRouter()

@router.get("/reports/stats", response_model=ReportStats)
def get_report_stats(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    province: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get statistics for reports with optional filters"""
    
    # Default to last 7 days if no dates provided
    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    
    # Base query
    query = db.query(models.PlateRead).join(
        models.Detection, models.PlateRead.detection_id == models.Detection.id
    ).join(
        models.Capture, models.Detection.capture_id == models.Capture.id
    ).filter(
        models.PlateRead.created_at >= start_dt,
        models.PlateRead.created_at < end_dt
    )
    
    if province:
        query = query.filter(models.PlateRead.province == province)
    if camera_id:
        query = query.filter(models.Capture.camera_id == camera_id)
    
    total_reads = query.count()
    verified_reads = query.filter(models.PlateRead.status == models.ReadStatus.VERIFIED).count()
    
    # ALPR vs MLPR
    alpr_count = db.query(func.count(models.VerificationJob.id)).join(
        models.PlateRead
    ).join(
        models.Detection, models.PlateRead.detection_id == models.Detection.id
    ).join(
        models.Capture, models.Detection.capture_id == models.Capture.id
    ).filter(
        models.VerificationJob.result_type == models.VerifyResultType.ALPR,
        models.PlateRead.created_at >= start_dt,
        models.PlateRead.created_at < end_dt
    )
    
    if province:
        alpr_count = alpr_count.filter(models.PlateRead.province == province)
    if camera_id:
        alpr_count = alpr_count.filter(models.Capture.camera_id == camera_id)
    
    alpr_total = alpr_count.scalar() or 0
    
    mlpr_count = db.query(func.count(models.VerificationJob.id)).join(
        models.PlateRead
    ).join(
        models.Detection, models.PlateRead.detection_id == models.Detection.id
    ).join(
        models.Capture, models.Detection.capture_id == models.Capture.id
    ).filter(
        models.VerificationJob.result_type == models.VerifyResultType.MLPR,
        models.PlateRead.created_at >= start_dt,
        models.PlateRead.created_at < end_dt
    )
    
    if province:
        mlpr_count = mlpr_count.filter(models.PlateRead.province == province)
    if camera_id:
        mlpr_count = mlpr_count.filter(models.Capture.camera_id == camera_id)
    
    mlpr_total = mlpr_count.scalar() or 0
    
    # Confidence distribution
    high_conf = query.filter(models.PlateRead.confidence >= 0.9).count()
    medium_conf = query.filter(
        models.PlateRead.confidence >= 0.7,
        models.PlateRead.confidence < 0.9
    ).count()
    low_conf = query.filter(models.PlateRead.confidence < 0.7).count()
    
    # Top provinces
    province_stats = db.query(
        models.PlateRead.province,
        func.count(models.PlateRead.id).label("count")
    ).join(
        models.Detection, models.PlateRead.detection_id == models.Detection.id
    ).join(
        models.Capture, models.Detection.capture_id == models.Capture.id
    ).filter(
        models.PlateRead.created_at >= start_dt,
        models.PlateRead.created_at < end_dt,
        models.PlateRead.province != ""
    )
    
    if camera_id:
        province_stats = province_stats.filter(models.Capture.camera_id == camera_id)
    
    province_stats = province_stats.group_by(
        models.PlateRead.province
    ).order_by(
        desc("count")
    ).limit(10).all()
    
    accuracy = (alpr_total / max(alpr_total + mlpr_total, 1)) * 100
    
    return ReportStats(
        total_reads=total_reads,
        verified_reads=verified_reads,
        alpr_total=alpr_total,
        mlpr_total=mlpr_total,
        accuracy=accuracy,
        high_confidence=high_conf,
        medium_confidence=medium_conf,
        low_confidence=low_conf,
        top_provinces=[{"province": p, "count": c} for p, c in province_stats],
        date_range={"start": start_date, "end": end_date}
    )


@router.get("/reports/activity")
def get_activity_log(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db)
):
    """Get recent activity log"""
    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    
    activities = db.query(
        models.PlateRead.id,
        models.PlateRead.plate_text,
        models.PlateRead.province,
        models.PlateRead.confidence,
        models.PlateRead.status,
        models.PlateRead.created_at,
        models.Capture.camera_id,
        models.Capture.source,
        models.Detection.crop_path
    ).join(
        models.Detection, models.PlateRead.detection_id == models.Detection.id
    ).join(
        models.Capture, models.Detection.capture_id == models.Capture.id
    ).filter(
        models.PlateRead.created_at >= start_dt,
        models.PlateRead.created_at < end_dt
    ).order_by(
        desc(models.PlateRead.created_at)
    ).limit(limit).all()
    
    return [
        {
            "id": a.id,
            "plate_text": a.plate_text,
            "province": a.province,
            "confidence": a.confidence,
            "status": a.status.value,
            "created_at": a.created_at.isoformat(),
            "camera_id": a.camera_id or "N/A",
            "source": a.source,
            "crop_url": make_image_url(a.crop_path)
        }
        for a in activities
    ]


@router.get("/reports/export")
def export_report(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Export report as CSV"""
    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    
    query = db.query(
        models.PlateRead.plate_text,
        models.PlateRead.province,
        models.PlateRead.confidence,
        models.PlateRead.status,
        models.PlateRead.created_at,
        models.Capture.camera_id,
        models.Capture.source,
        models.VerificationJob.result_type
    ).join(
        models.Detection, models.PlateRead.detection_id == models.Detection.id
    ).join(
        models.Capture, models.Detection.capture_id == models.Capture.id
    ).outerjoin(
        models.VerificationJob, models.PlateRead.id == models.VerificationJob.read_id
    ).filter(
        models.PlateRead.created_at >= start_dt,
        models.PlateRead.created_at < end_dt
    )
    
    if province:
        query = query.filter(models.PlateRead.province == province)
    if camera_id:
        query = query.filter(models.Capture.camera_id == camera_id)
    
    rows = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Plate", "Province", "Confidence", "Status", 
        "Created At", "Camera ID", "Source", "Result Type"
    ])
    
    for r in rows:
        writer.writerow([
            r.plate_text,
            r.province,
            f"{r.confidence:.3f}",
            r.status.value,
            r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            r.camera_id or "N/A",
            r.source,
            r.result_type.value if r.result_type else "N/A"
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=report_{start_date}_{end_date}.csv"}
    )


@router.get("/reports/accuracy")
def get_accuracy_metrics(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Get daily accuracy metrics"""
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    
    results = []
    current = start_dt
    
    while current < end_dt:
        next_day = current + timedelta(days=1)
        
        alpr = db.query(func.count(models.VerificationJob.id)).join(
            models.PlateRead
        ).filter(
            models.VerificationJob.result_type == models.VerifyResultType.ALPR,
            models.PlateRead.created_at >= current,
            models.PlateRead.created_at < next_day
        ).scalar() or 0
        
        mlpr = db.query(func.count(models.VerificationJob.id)).join(
            models.PlateRead
        ).filter(
            models.VerificationJob.result_type == models.VerifyResultType.MLPR,
            models.PlateRead.created_at >= current,
            models.PlateRead.created_at < next_day
        ).scalar() or 0
        
        total = alpr + mlpr
        accuracy = (alpr / max(total, 1)) * 100
        
        results.append({
            "date": current.strftime("%Y-%m-%d"),
            "alpr": alpr,
            "mlpr": mlpr,
            "total": total,
            "accuracy": accuracy
        })
        
        current = next_day
    
    return results