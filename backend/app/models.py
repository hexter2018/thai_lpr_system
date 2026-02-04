# models.py
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    String,
    Text,
    DateTime,
    Float,
    ForeignKey,
    Enum as SAEnum,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanStatus(str, enum.Enum):
    PENDING = "PENDING"
    ALPR = "ALPR"
    MLPR = "MLPR"


class MasterData(Base):
    __tablename__ = "master_data"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Plate text (e.g. "1กก 1234" or "1กก1234" depending on your convention)
    license_number: Mapped[str] = mapped_column(Text, nullable=False)
    province: Mapped[str] = mapped_column(Text, nullable=False)

    owner_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vehicle_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    scan_logs: Mapped[List["ScanLog"]] = relationship(
        back_populates="master",
        lazy="selectin",
    )

    __table_args__ = (
        # Commonly you want master uniqueness per (plate, province)
        UniqueConstraint("license_number", "province", name="uq_master_plate_province"),
        Index("ix_master_plate", "license_number"),
        Index("ix_master_province", "province"),
    )


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    master_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("master_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    original_image_path: Mapped[str] = mapped_column(Text, nullable=False)
    cropped_plate_image_path: Mapped[str] = mapped_column(Text, nullable=False)

    detected_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_province: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[ScanStatus] = mapped_column(
        SAEnum(ScanStatus, name="scan_status"),
        nullable=False,
        default=ScanStatus.PENDING,
        index=True,
    )

    # Store what humans corrected + audit data
    # Example:
    # {
    #   "is_correct": false,
    #   "corrected_license": "1กก 1234",
    #   "corrected_province": "กรุงเทพมหานคร",
    #   "reviewer": "user123",
    #   "reviewed_at": "2026-02-04T12:34:56Z"
    # }
    verification_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    master: Mapped[Optional[MasterData]] = relationship(
        back_populates="scan_logs",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_scan_logs_created_at", "created_at"),
        Index("ix_scan_logs_status_created_at", "status", "created_at"),
    )
