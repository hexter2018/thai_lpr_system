import enum
from datetime import datetime
from sqlalchemy import (
    String, Integer, DateTime, Enum, Float, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

class ReadStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"

class VerifyResultType(str, enum.Enum):
    ALPR = "ALPR"   # confirmed correct after human verify
    MLPR = "MLPR"   # corrected by human

class Capture(Base):
    __tablename__ = "captures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="UPLOAD")  # UPLOAD/RTSP
    camera_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    original_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))

    detections: Mapped[list["Detection"]] = relationship(back_populates="capture")

class Detection(Base):
    __tablename__ = "detections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("captures.id"), index=True)
    crop_path: Mapped[str] = mapped_column(Text)
    det_conf: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[str] = mapped_column(Text, default="")  # JSON string

    capture: Mapped["Capture"] = relationship(back_populates="detections")
    reads: Mapped[list["PlateRead"]] = relationship(back_populates="detection")

class PlateRead(Base):
    __tablename__ = "plate_reads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("detections.id"), index=True)

    plate_text: Mapped[str] = mapped_column(String(32), default="")
    plate_text_norm: Mapped[str] = mapped_column(String(32), default="")
    province: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[ReadStatus] = mapped_column(Enum(ReadStatus), default=ReadStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    detection: Mapped["Detection"] = relationship(back_populates="reads")
    verification: Mapped["VerificationJob"] = relationship(back_populates="read", uselist=False)

class VerificationJob(Base):
    __tablename__ = "verification_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    read_id: Mapped[int] = mapped_column(ForeignKey("plate_reads.id"), unique=True)

    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    corrected_text: Mapped[str | None] = mapped_column(String(32), nullable=True)
    corrected_province: Mapped[str | None] = mapped_column(String(64), nullable=True)

    result_type: Mapped[VerifyResultType | None] = mapped_column(Enum(VerifyResultType), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    read: Mapped["PlateRead"] = relationship(back_populates="verification")

class MasterPlate(Base):
    __tablename__ = "master_plates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_text_norm: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_text: Mapped[str] = mapped_column(String(32), default="")
    province: Mapped[str] = mapped_column(String(64), default="")

    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    count_seen: Mapped[int] = mapped_column(Integer, default=1)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)

class FeedbackSample(Base):
    __tablename__ = "feedback_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crop_path: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str] = mapped_column(String(32))
    corrected_province: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(100), default="MLPR")
    used_in_train: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    rtsp_url: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
