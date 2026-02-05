from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from app.core.config import settings

router = APIRouter()

@router.get("/images")
def get_image(path: str):
    # Very simple dev-only file server: expects an absolute path inside STORAGE_DIR
    # Frontend passes the stored path; we ensure it is under STORAGE_DIR for safety.
    storage = Path(settings.storage_dir).resolve()
    p = Path(path).resolve()
    if storage not in p.parents and p != storage:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(p))
