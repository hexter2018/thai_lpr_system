import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db import models
from app.services.queue import enqueue_process_capture

router = APIRouter()
logger = logging.getLogger(__name__)

def resolve_storage_dir() -> Path:
    preferred = Path(settings.storage_dir)
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe_path = preferred / ".write_test"
        probe_path.write_bytes(b"ok")
        probe_path.unlink(missing_ok=True)
        return preferred
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Storage directory permission denied: {preferred}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Storage directory is not writable: {preferred}",
        ) from exc

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _store_file(upload: UploadFile, storage: Path) -> tuple[Path, str]:
    ext = Path(upload.filename or "upload.jpg").suffix.lower() or ".jpg"
    fname = f"{uuid.uuid4().hex}{ext}"
    out_path = storage / "original" / fname
    out_path.parent.mkdir(parents=True, exist_ok=True)

    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    out_path.write_bytes(content)
    return out_path, sha256_file(out_path)


def _save_capture(db: Session, out_path: Path, digest: str) -> models.Capture:
    cap = models.Capture(source="UPLOAD", original_path=str(out_path), sha256=digest)
    try:
        db.add(cap)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to save uploaded capture", extra={"path": str(out_path)})
        raise HTTPException(status_code=500, detail="Failed to save upload metadata") from exc

    db.refresh(cap)
    return cap

@router.post("/upload")
async def upload_one(file: UploadFile = File(...), db: Session = Depends(get_db)):
    storage = resolve_storage_dir()
    try:
        out_path, digest = await _store_file(file, storage)
        cap = _save_capture(db, out_path, digest)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected upload failure")
        raise HTTPException(status_code=500, detail="Upload failed unexpectedly") from exc

    queued = enqueue_process_capture(cap.id, str(out_path))

    return {
        "capture_id": cap.id,
        "original_path": str(out_path),
        "queued": queued,
        "message": None if queued else "Capture saved but queue is unavailable. Start worker/redis and retry processing.",
    }

@router.post("/upload/batch")
async def upload_batch(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    storage = resolve_storage_dir()

    ids = []
    queue_failures = []
    for file in files:
        try:
            out_path, digest = await _store_file(file, storage)
            cap = _save_capture(db, out_path, digest)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unexpected batch upload failure")
            raise HTTPException(status_code=500, detail="Batch upload failed unexpectedly") from exc

        queued = enqueue_process_capture(cap.id, str(out_path))
        if not queued:
            queue_failures.append(cap.id)
        ids.append(cap.id)

    return {
        "capture_ids": ids,
        "count": len(ids),
        "queued_count": len(ids) - len(queue_failures),
        "failed_to_queue": queue_failures,
        "message": None if not queue_failures else "Some captures were saved but not queued. Start worker/redis and retry processing.",
    }
