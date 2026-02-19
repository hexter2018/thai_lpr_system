# backend/app/db/models.py
"""
Database Models for Thai LPR V2 with Vehicle Tracking
"""
import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Enum, Float, Boolean, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


# ===================== Enums =====================
class ReadStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


class VerifyResultType(str, enum.Enum):
    ALPR = "ALPR"   # AI correct
    MLPR = "MLPR"   # Manual correction


class CameraStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class VehicleType(str, enum.Enum):
    CAR = "CAR"
    TRUCK = "TRUCK"
    MOTORCYCLE = "MOTORCYCLE"
    BUS = "BUS"
    UNKNOWN = "UNKNOWN"


# ===================== Camera Management =====================
class Camera(Base):
    """RTSP Camera Configuration with Zone Settings"""
    __tablename__ = "cameras"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    rtsp_url: Mapped[str] = mapped_column(Text)
    
    # Zone Configuration (JSON: polygon points)
    zone_polygon: Mapped[dict] = mapped_column(JSON, nullable=True)
    zone_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Status
    status: Mapped[CameraStatus] = mapped_column(Enum(CameraStatus), default=CameraStatus.INACTIVE)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Stream Settings
    fps_target: Mapped[float] = mapped_column(Float, default=10.0)
    codec: Mapped[str] = mapped_column(String(20), default="h264")  # h264, h265
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    vehicle_tracks: Mapped[list["VehicleTrack"]] = relationship(back_populates="camera")


class CameraStats(Base):
    """Real-time Camera Statistics"""
    __tablename__ = "camera_stats"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(100), ForeignKey("cameras.camera_id"), index=True)
    
    # Metrics (last 5 minutes window)
    fps_actual: Mapped[float] = mapped_column(Float, default=0.0)
    vehicle_count: Mapped[int] = mapped_column(Integer, default=0)
    lpr_success_count: Mapped[int] = mapped_column(Integer, default=0)
    lpr_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Success Rate (%)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Timestamp
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ===================== Vehicle Tracking =====================
class VehicleTrack(Base):
    """Vehicle Track Records (ByteTrack)"""
    __tablename__ = "vehicle_tracks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(100), ForeignKey("cameras.camera_id"), index=True)
    
    # Tracking Info
    track_id: Mapped[int] = mapped_column(Integer, index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(Enum(VehicleType), default=VehicleType.UNKNOWN)
    
    # Zone Trigger Status
    entered_zone: Mapped[bool] = mapped_column(Boolean, default=False)
    entered_zone_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    lpr_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    lpr_triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Bounding Box (last known position)
    bbox: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    # Timestamps
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    camera: Mapped["Camera"] = relationship(back_populates="vehicle_tracks")
    plate_reads: Mapped[list["PlateRead"]] = relationship(back_populates="vehicle_track")


# ===================== Capture & Detection =====================
class Capture(Base):
    """Image Capture Records"""
    __tablename__ = "captures"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="RTSP")
    camera_id: Mapped[str] = mapped_column(String(100), nullable=True)
    track_id: Mapped[int] = mapped_column(Integer, nullable=True)  # Vehicle track ID
    
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    original_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    
    # Relationships
    detections: Mapped[list["Detection"]] = relationship(back_populates="capture")


class Detection(Base):
    """Plate Detection Results"""
    __tablename__ = "detections"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("captures.id"), index=True)
    
    crop_path: Mapped[str] = mapped_column(Text)
    det_conf: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    # Relationships
    capture: Mapped["Capture"] = relationship(back_populates="detections")
    reads: Mapped[list["PlateRead"]] = relationship(back_populates="detection")


# ===================== OCR & Verification =====================
class PlateRead(Base):
    """OCR Results with Master Data Integration"""
    __tablename__ = "plate_reads"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("detections.id"), index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("vehicle_tracks.id"), nullable=True, index=True)
    
    # OCR Results
    plate_text: Mapped[str] = mapped_column(String(32), default="")
    plate_text_norm: Mapped[str] = mapped_column(String(32), default="", index=True)
    province: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    
    # OCR Metadata
    ocr_raw: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    # Master Data Match
    master_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    master_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Status
    status: Mapped[ReadStatus] = mapped_column(Enum(ReadStatus), default=ReadStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    detection: Mapped["Detection"] = relationship(back_populates="reads")
    vehicle_track: Mapped["VehicleTrack"] = relationship(back_populates="plate_reads")
    verification: Mapped["VerificationJob"] = relationship(back_populates="read", uselist=False)


class VerificationJob(Base):
    """Human Verification Records"""
    __tablename__ = "verification_jobs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    read_id: Mapped[int] = mapped_column(ForeignKey("plate_reads.id"), unique=True)
    
    # Verification Details
    assigned_to: Mapped[str] = mapped_column(String(100), nullable=True)
    corrected_text: Mapped[str] = mapped_column(String(32), nullable=True)
    corrected_province: Mapped[str] = mapped_column(String(64), nullable=True)
    
    result_type: Mapped[VerifyResultType] = mapped_column(Enum(VerifyResultType), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=True)
    
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    read: Mapped["PlateRead"] = relationship(back_populates="verification")


# ===================== Master Data =====================
class MasterPlate(Base):
    """Master Database for Known Plates"""
    __tablename__ = "master_plates"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_text_norm: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_text: Mapped[str] = mapped_column(String(32), default="")
    province: Mapped[str] = mapped_column(String(64), default="")
    
    # Metadata
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    count_seen: Mapped[int] = mapped_column(Integer, default=1)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Vehicle Info (optional)
    vehicle_type: Mapped[VehicleType] = mapped_column(Enum(VehicleType), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)


# ===================== Active Learning =====================
class MLPRSample(Base):
    """MLPR Samples for EasyOCR Retraining"""
    __tablename__ = "mlpr_samples"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    read_id: Mapped[int] = mapped_column(ForeignKey("plate_reads.id"))
    
    # Training Data
    crop_path: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str] = mapped_column(String(32))
    corrected_province: Mapped[str] = mapped_column(String(64))
    
    # Export Status
    exported: Mapped[bool] = mapped_column(Boolean, default=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    used_in_training: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ===================== System Analytics =====================
class SystemMetrics(Base):
    """System-wide Performance Metrics"""
    __tablename__ = "system_metrics"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    # Counts
    total_vehicles: Mapped[int] = mapped_column(Integer, default=0)
    total_lpr_attempts: Mapped[int] = mapped_column(Integer, default=0)
    total_lpr_success: Mapped[int] = mapped_column(Integer, default=0)
    total_alpr: Mapped[int] = mapped_column(Integer, default=0)
    total_mlpr: Mapped[int] = mapped_column(Integer, default=0)
    
    # Success Rate
    overall_success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    alpr_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Master Data Stats
    master_count: Mapped[int] = mapped_column(Integer, default=0)
    master_match_rate: Mapped[float] = mapped_column(Float, default=0.0)
