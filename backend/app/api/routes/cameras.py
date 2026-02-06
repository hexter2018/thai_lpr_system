from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.schemas.cameras import CameraOut, CameraUpsertIn

router = APIRouter()

@router.get("/cameras", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db)):
    cameras = db.query(models.Camera).order_by(models.Camera.id.asc()).all()
    return [CameraOut(**camera.__dict__) for camera in cameras]

@router.post("/cameras", response_model=CameraOut)
def upsert_camera(payload: CameraUpsertIn, db: Session = Depends(get_db)):
    camera = db.query(models.Camera).filter(models.Camera.camera_id == payload.camera_id).first()
    if camera:
        camera.name = payload.name
        camera.rtsp_url = payload.rtsp_url
        camera.enabled = payload.enabled
    else:
        camera = models.Camera(
            camera_id=payload.camera_id,
            name=payload.name,
            rtsp_url=payload.rtsp_url,
            enabled=payload.enabled,
        )
        db.add(camera)
    db.commit()
    db.refresh(camera)
    return CameraOut(**camera.__dict__)
