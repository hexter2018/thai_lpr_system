import os, hashlib, uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db import models
from app.services.queue import enqueue_process_capture

router = APIRouter()

def resolve_storage_dir() -> Path:
    preferred = Path(settings.storage_dir)
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        if os.access(preferred, os.W_OK):
            return preferred
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Storage directory is not writable: {preferred}",
            )
    except PermissionError:
        raise HTTPException(
            status_code=500, 
            detail=f"Storage directory permission denied: {preferred}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Storage directory could not be created: {preferred}, error: {str(e)}",
        )

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

@router.post("/upload")
async def upload_one(file: UploadFile = File(...), db: Session = Depends(get_db)):
    storage = resolve_storage_dir()

    ext = Path(file.filename).suffix.lower() or ".jpg"
    fname = f"{uuid.uuid4().hex}{ext}"
    out_path = storage / "original" / fname
    out_path.parent.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    out_path.write_bytes(content)
    digest = sha256_file(out_path)

    cap = models.Capture(source="UPLOAD", original_path=str(out_path), sha256=digest)
    db.add(cap)
    db.commit()
    db.refresh(cap)

    enqueue_process_capture(cap.id, str(out_path))

    return {"capture_id": cap.id, "original_path": str(out_path)}

@router.post("/upload/batch")
async def upload_batch(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    storage = resolve_storage_dir()

    ids = []
    for file in files:
        ext = Path(file.filename).suffix.lower() or ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        out_path = storage / "original" / fname
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(await file.read())
        digest = sha256_file(out_path)

        cap = models.Capture(source="UPLOAD", original_path=str(out_path), sha256=digest)
        db.add(cap)
        db.commit()
        db.refresh(cap)

        enqueue_process_capture(cap.id, str(out_path))
        ids.append(cap.id)

    return {"capture_ids": ids, "count": len(ids)}