# main.py
from __future__ import annotations

import os
from datetime import datetime, timezone

import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from models import MasterData, ScanLog, ScanStatus
from schemas import RecognizeResponse, VerifyRequest, StatsResponse
from lpr_processor import LPRProcessor
from storage import save_image_bgr
from api_queue import router as queue_router
from fastapi.middleware.cors import CORSMiddleware


STORAGE_BASE = os.getenv("STORAGE_BASE", "./storage")  # store originals + crops here

app = FastAPI(title="Thai LPR System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(queue_router)

# Load once (GPU model + OCR)
lpr = LPRProcessor(model_dir=os.getenv("MODEL_DIR", "./models"))


def _decode_upload_to_bgr(file_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Invalid image")
    return img


@app.post("/api/recognize", response_model=RecognizeResponse)
async def recognize(
    image: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> RecognizeResponse:
    file_bytes = await image.read()
    try:
        img_bgr = _decode_upload_to_bgr(file_bytes)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image file")

    result = lpr.recognize(img_bgr)
    if result["cropped_image"] is None:
        # Still log it (optional), but here we fail fast
        raise HTTPException(status_code=422, detail="No plate detected")

    # Persist images
    original_rel = save_image_bgr(img_bgr, STORAGE_BASE, "orig")
    cropped_rel = save_image_bgr(result["cropped_image"], STORAGE_BASE, "crop")

    license_text = result["license_text"]
    province = result["province"]
    confidence = float(result["confidence"])

    # Master match
    master_id = None
    if license_text and province:
        q = select(MasterData).where(
            MasterData.license_number == license_text,
            MasterData.province == province,
        ).limit(1)
        master = (await session.execute(q)).scalars().first()
        if master:
            master_id = master.id

    status = ScanStatus.ALPR if confidence > 0.95 else ScanStatus.PENDING

    log = ScanLog(
        master_id=master_id,
        original_image_path=os.path.join("storage", original_rel).replace("\\", "/"),
        cropped_plate_image_path=os.path.join("storage", cropped_rel).replace("\\", "/"),
        detected_text=license_text or None,
        detected_province=province or None,
        confidence_score=confidence,
        status=status,
        verification_result=None,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)

    return RecognizeResponse(
        log_id=log.id,
        license_text=license_text,
        province=province,
        confidence=confidence,
        status=log.status.value,
        master_id=log.master_id,
        original_image_path=log.original_image_path,
        cropped_plate_image_path=log.cropped_plate_image_path,
        debug=result.get("debug"),
    )


@app.post("/api/verify/{log_id}")
async def verify(
    log_id: int,
    payload: VerifyRequest,
    session: AsyncSession = Depends(get_session),
):
    q = select(ScanLog).where(ScanLog.id == log_id).limit(1)
    log = (await session.execute(q)).scalars().first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Business logic:
    # - If is_correct True -> status ALPR, keep detected values (or accept corrected as canonical)
    # - If is_correct False -> status MLPR, store corrected data in verification_result
    if payload.is_correct:
        log.status = ScanStatus.ALPR
        verification = {
            "is_correct": True,
            "confirmed_license": log.detected_text,
            "confirmed_province": log.detected_province,
            "reviewed_at": now_iso,
        }
        # Upsert using detected values (or corrected values if you prefer)
        up_license = (log.detected_text or payload.corrected_license).strip()
        up_province = (log.detected_province or payload.corrected_province).strip()
    else:
        log.status = ScanStatus.MLPR
        verification = {
            "is_correct": False,
            "corrected_license": payload.corrected_license.strip(),
            "corrected_province": payload.corrected_province.strip(),
            "reviewed_at": now_iso,
        }
        up_license = payload.corrected_license.strip()
        up_province = payload.corrected_province.strip()

    log.verification_result = verification

    # Upsert MasterData: (license_number, province) unique
    mq = select(MasterData).where(
        MasterData.license_number == up_license,
        MasterData.province == up_province,
    ).limit(1)
    master = (await session.execute(mq)).scalars().first()
    if not master:
        master = MasterData(
            license_number=up_license,
            province=up_province,
            owner_name=None,
            vehicle_type=None,
        )
        session.add(master)
        await session.flush()  # get master.id without commit yet

    log.master_id = master.id

    await session.commit()
    return {
        "log_id": log.id,
        "status": log.status.value,
        "master_id": log.master_id,
        "verification_result": log.verification_result,
    }


@app.get("/api/dashboard/stats", response_model=StatsResponse)
async def dashboard_stats(session: AsyncSession = Depends(get_session)) -> StatsResponse:
    try:
        total = await session.scalar(select(func.count(ScanLog.id)))
        alpr = await session.scalar(select(func.count(ScanLog.id)).where(ScanLog.status == ScanStatus.ALPR))
        mlpr = await session.scalar(select(func.count(ScanLog.id)).where(ScanLog.status == ScanStatus.MLPR))
        pending = await session.scalar(select(func.count(ScanLog.id)).where(ScanLog.status == ScanStatus.PENDING))

        total = int(total or 0)
        alpr = int(alpr or 0)
        mlpr = int(mlpr or 0)
        pending = int(pending or 0)

        # Overall accuracy (simple): ALPR / total
        accuracy = (alpr / total * 100.0) if total > 0 else 0.0

        # Verified accuracy: ALPR / (ALPR + MLPR) among reviewed
        reviewed = alpr + mlpr
        accuracy_verified = (alpr / reviewed * 100.0) if reviewed > 0 else 0.0

        return StatsResponse(
            total_scanned=total,
            alpr_count=alpr,
            mlpr_count=mlpr,
            pending_count=pending,
            accuracy_percent=round(accuracy, 2),
            accuracy_verified_percent=round(accuracy_verified, 2),
        )
    except Exception as e:
        # Return a 503 with a readable message so the frontend can display it
        raise HTTPException(status_code=503, detail=f"Failed to load stats: {e}")


@app.get("/api/health")
async def health_check(session: AsyncSession = Depends(get_session)):
    """Lightweight health endpoint to verify DB connectivity."""
    try:
        # simple lightweight query
        await session.scalar(select(func.count(ScanLog.id)).limit(1))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
