"""Main FastAPI application"""
import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
from typing import List, Optional

from app.db.session import get_db
from app.db.models import (
    Camera, VehicleTrack, Capture, Detection, PlateRead,
    VerificationJob, MasterPlate, MLPRSample, CameraStats, SystemMetrics
)

app = FastAPI(title="Thai LPR V2 API", version="2.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "thai-lpr-backend"}


# ==================== Camera Management ====================

@app.get("/api/cameras")
def list_cameras(db: Session = Depends(get_db)):
    """List all cameras"""
    cameras = db.query(Camera).all()
    return [
        {
            "camera_id": c.camera_id,
            "name": c.name,
            "rtsp_url": c.rtsp_url,
            "zone_enabled": c.zone_enabled,
            "zone_polygon": c.zone_polygon,
            "status": c.status,
            "fps_target": c.fps_target,
            "codec": c.codec,
        }
        for c in cameras
    ]


@app.post("/api/cameras")
def create_or_update_camera(camera_data: dict, db: Session = Depends(get_db)):
    """Create or update a camera"""
    camera_id = camera_data.get("camera_id")
    
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    
    if camera:
        # Update existing
        for key, value in camera_data.items():
            if hasattr(camera, key):
                setattr(camera, key, value)
    else:
        # Create new
        camera = Camera(**camera_data)
        db.add(camera)
    
    db.commit()
    db.refresh(camera)
    
    return {"success": True, "camera_id": camera.camera_id}


@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: str, db: Session = Depends(get_db)):
    """Delete a camera"""
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if camera:
        db.delete(camera)
        db.commit()
        return {"success": True}
    return {"success": False, "error": "Camera not found"}


@app.get("/api/cameras/{camera_id}/stats")
def get_camera_stats(camera_id: str, db: Session = Depends(get_db)):
    """Get camera statistics"""
    # Get latest stats
    stats = db.query(CameraStats).filter(
        CameraStats.camera_id == camera_id
    ).order_by(CameraStats.window_end.desc()).first()
    
    if stats:
        return {
            "fps_actual": stats.fps_actual,
            "vehicle_count": stats.vehicle_count,
            "lpr_success_count": stats.lpr_success_count,
            "lpr_fail_count": stats.lpr_fail_count,
            "success_rate": stats.success_rate,
        }
    
    return {
        "fps_actual": 0.0,
        "vehicle_count": 0,
        "lpr_success_count": 0,
        "lpr_fail_count": 0,
        "success_rate": 0.0,
    }


# ==================== Vehicle Tracking ====================

@app.get("/api/tracks/{camera_id}")
def get_active_tracks(camera_id: str, db: Session = Depends(get_db)):
    """Get active tracks for a camera"""
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    
    tracks = db.query(VehicleTrack).filter(
        and_(
            VehicleTrack.camera_id == camera_id,
            VehicleTrack.last_seen >= cutoff
        )
    ).all()
    
    result = []
    for track in tracks:
        # Get plate if available
        plate_read = db.query(PlateRead).filter(
            PlateRead.track_id == track.track_id
        ).order_by(PlateRead.created_at.desc()).first()
        
        result.append({
            "track_id": track.track_id,
            "vehicle_type": track.vehicle_type,
            "entered_zone": track.entered_zone,
            "lpr_triggered": track.lpr_triggered,
            "plate_text": plate_read.plate_text if plate_read else None,
            "plate_confidence": plate_read.confidence if plate_read else None,
            "first_seen": track.first_seen.isoformat(),
            "last_seen": track.last_seen.isoformat(),
            "duration_seconds": int((track.last_seen - track.first_seen).total_seconds()),
        })
    
    return result


@app.get("/api/tracks/history")
def get_track_history(
    camera_id: Optional[str] = None,
    date_range: str = "today",
    plate_text: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get track history"""
    # Calculate date range
    now = datetime.utcnow()
    if date_range == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_range == "yesterday":
        start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        now = start_date + timedelta(days=1)
    elif date_range == "week":
        start_date = now - timedelta(days=7)
    elif date_range == "month":
        start_date = now - timedelta(days=30)
    else:
        start_date = now - timedelta(days=1)
    
    query = db.query(VehicleTrack).filter(
        VehicleTrack.first_seen >= start_date
    )
    
    if camera_id:
        query = query.filter(VehicleTrack.camera_id == camera_id)
    
    tracks = query.order_by(VehicleTrack.first_seen.desc()).limit(100).all()
    
    result = []
    for track in tracks:
        plate_read = db.query(PlateRead).filter(
            PlateRead.track_id == track.track_id
        ).first()
        
        # Filter by plate text if provided
        if plate_text and plate_read:
            if plate_text.lower() not in plate_read.plate_text.lower():
                continue
        
        camera = db.query(Camera).filter(Camera.camera_id == track.camera_id).first()
        
        result.append({
            "track_id": track.track_id,
            "camera_name": camera.name if camera else track.camera_id,
            "vehicle_type": track.vehicle_type,
            "plate_text": plate_read.plate_text if plate_read else None,
            "province": plate_read.province if plate_read else None,
            "plate_confidence": plate_read.confidence if plate_read else None,
            "verification_status": plate_read.status if plate_read else None,
            "first_seen": track.first_seen.isoformat(),
        })
    
    return result


# ==================== License Plate Verification ====================

@app.get("/api/reads/pending")
def get_pending_reads(db: Session = Depends(get_db)):
    """Get pending plate reads for verification"""
    reads = db.query(PlateRead).filter(
        PlateRead.status == "PENDING"
    ).order_by(PlateRead.created_at.desc()).limit(50).all()
    
    result = []
    for read in reads:
        track = db.query(VehicleTrack).filter(
            VehicleTrack.track_id == read.track_id
        ).first()
        
        camera = db.query(Camera).filter(
            Camera.camera_id == track.camera_id
        ).first() if track else None
        
        detection = db.query(Detection).filter(
            Detection.id == read.detection_id
        ).first()
        
        result.append({
            "id": read.id,
            "plate_text": read.plate_text,
            "province": read.province,
            "confidence": read.confidence,
            "track_id": read.track_id,
            "camera_name": camera.name if camera else "Unknown",
            "crop_path": detection.crop_path if detection else None,
            "captured_at": read.created_at.isoformat(),
        })
    
    return result


@app.post("/api/reads/{read_id}/verify")
def verify_plate_read(read_id: int, verification: dict, db: Session = Depends(get_db)):
    """Verify or correct a plate read"""
    read = db.query(PlateRead).filter(PlateRead.id == read_id).first()
    
    if not read:
        return {"success": False, "error": "Read not found"}
    
    is_correct = verification.get("is_correct", False)
    
    if is_correct:
        # ALPR - automatic verification
        read.status = "VERIFIED"
        result_type = "ALPR"
    else:
        # MLPR - manual correction
        corrected_text = verification.get("corrected_text")
        corrected_province = verification.get("corrected_province")
        
        if not corrected_text:
            return {"success": False, "error": "Corrected text required"}
        
        read.status = "VERIFIED"
        result_type = "MLPR"
        
        # Create verification job
        job = VerificationJob(
            read_id=read.id,
            corrected_text=corrected_text,
            corrected_province=corrected_province,
            result_type=result_type,
            verified_at=datetime.utcnow()
        )
        db.add(job)
        
        # Update master plate database
        normalized = corrected_text.upper().replace(" ", "")
        master = db.query(MasterPlate).filter(
            MasterPlate.plate_text_norm == normalized
        ).first()
        
        if master:
            master.count_seen += 1
            master.last_seen = datetime.utcnow()
        else:
            master = MasterPlate(
                plate_text_norm=normalized,
                display_text=corrected_text,
                province=corrected_province,
                confidence=read.confidence,
                last_seen=datetime.utcnow(),
                count_seen=1
            )
            db.add(master)
        
        # Create MLPR sample for training
        detection = db.query(Detection).filter(
            Detection.id == read.detection_id
        ).first()
        
        if detection:
            sample = MLPRSample(
                read_id=read.id,
                crop_path=detection.crop_path,
                corrected_text=corrected_text,
                corrected_province=corrected_province,
                exported=False
            )
            db.add(sample)
    
    db.commit()
    
    return {"success": True, "result_type": result_type}


# ==================== Analytics ====================

@app.get("/api/analytics/dashboard")
def get_dashboard_analytics(db: Session = Depends(get_db)):
    """Get dashboard analytics"""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Total cameras
    total_cameras = db.query(func.count(Camera.camera_id)).scalar()
    active_cameras = db.query(func.count(Camera.camera_id)).filter(
        Camera.status == "active"
    ).scalar()
    
    # Vehicles today
    total_vehicles_today = db.query(func.count(VehicleTrack.track_id)).filter(
        VehicleTrack.first_seen >= today_start
    ).scalar() or 0
    
    # LPR attempts and success
    total_lpr_attempts_today = db.query(func.count(PlateRead.id)).filter(
        PlateRead.created_at >= today_start
    ).scalar() or 0
    
    total_lpr_success_today = db.query(func.count(PlateRead.id)).filter(
        and_(
            PlateRead.created_at >= today_start,
            PlateRead.status == "VERIFIED"
        )
    ).scalar() or 0
    
    success_rate_today = (
        (total_lpr_success_today / total_lpr_attempts_today * 100)
        if total_lpr_attempts_today > 0 else 0.0
    )
    
    # ALPR vs MLPR
    alpr_count_today = db.query(func.count(VerificationJob.id)).filter(
        and_(
            VerificationJob.verified_at >= today_start,
            VerificationJob.result_type == "ALPR"
        )
    ).scalar() or 0
    
    mlpr_count_today = db.query(func.count(VerificationJob.id)).filter(
        and_(
            VerificationJob.verified_at >= today_start,
            VerificationJob.result_type == "MLPR"
        )
    ).scalar() or 0
    
    # ALPR accuracy (correct without manual intervention)
    alpr_accuracy = (
        (alpr_count_today / total_lpr_success_today * 100)
        if total_lpr_success_today > 0 else 0.0
    )
    
    # Master plate count
    master_plate_count = db.query(func.count(MasterPlate.id)).scalar() or 0
    
    # Master match rate
    master_matched_today = db.query(func.count(PlateRead.id)).filter(
        and_(
            PlateRead.created_at >= today_start,
            PlateRead.master_matched == True
        )
    ).scalar() or 0
    
    master_match_rate = (
        (master_matched_today / total_lpr_attempts_today * 100)
        if total_lpr_attempts_today > 0 else 0.0
    )
    
    # Pending verification
    pending_verification = db.query(func.count(PlateRead.id)).filter(
        PlateRead.status == "PENDING"
    ).scalar() or 0
    
    return {
        "total_cameras": total_cameras,
        "active_cameras": active_cameras,
        "total_vehicles_today": total_vehicles_today,
        "total_lpr_attempts_today": total_lpr_attempts_today,
        "total_lpr_success_today": total_lpr_success_today,
        "success_rate_today": success_rate_today,
        "alpr_count_today": alpr_count_today,
        "mlpr_count_today": mlpr_count_today,
        "alpr_accuracy": alpr_accuracy,
        "master_plate_count": master_plate_count,
        "master_match_rate": master_match_rate,
        "pending_verification": pending_verification,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)