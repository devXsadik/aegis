"""Vehicle watchlist and the managed vehicle lists (types, colours, makes/models)."""

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.db.database import Base

WL_STATUSES = ("pending", "active", "rejected", "revoked", "expired")
RISK_LEVELS = ("low", "medium", "high", "critical")


class WatchlistVehicle(Base):
    __tablename__ = "watchlist_vehicles"

    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String(20), unique=True, nullable=False, index=True)      # V-XXXXXXXX
    plate_raw = Column(String(60), nullable=True)                          # as typed (Bangla or English)
    plate_canonical = Column(String(60), nullable=True, index=True)        # DHAKA-METRO-GA-12-3456
    vehicle_type = Column(String(30), nullable=True, index=True)           # catalog code
    color_primary = Column(String(20), nullable=True, index=True)
    color_secondary = Column(String(20), nullable=True)
    make_model = Column(String(60), nullable=True, index=True)             # catalog code, e.g. toyota_axio
    marks = Column(Text, nullable=True)                                    # stickers, damage, branding
    notes = Column(Text, nullable=True)
    linked_person_id = Column(Integer, ForeignKey("known_persons.id", ondelete="SET NULL"), nullable=True)
    risk_level = Column(String(10), nullable=False, default="medium")

    # governance — same rules as people
    case_no = Column(String(60), nullable=False, index=True)
    offence = Column(String(120), nullable=True)
    issuing_authority = Column(String(120), nullable=False)
    legal_basis = Column(Text, nullable=False)
    wl_status = Column(String(12), nullable=False, default="pending", index=True)
    requested_by = Column(Integer, nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    decision_note = Column(Text, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    photos = relationship("WatchlistVehiclePhoto", back_populates="vehicle", cascade="all, delete-orphan")


class WatchlistVehiclePhoto(Base):
    __tablename__ = "watchlist_vehicle_photos"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("watchlist_vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    image = Column(LargeBinary, nullable=False)          # sealed at rest (backend/utils/at_rest.py)
    encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
    content_type = Column(String(30), nullable=False, default="image/jpeg")
    sha256 = Column(String(64), nullable=False, index=True)
    embedding = Column(LargeBinary, nullable=True)       # vehicle re-ID vector (Phase 7)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vehicle = relationship("WatchlistVehicle", back_populates="photos")


class VehicleCatalog(Base):
    """Managed lists: kind = type | color | make | model. A model's parent is its make."""
    __tablename__ = "vehicle_catalog"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(10), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_en = Column(String(60), nullable=False)
    name_bn = Column(String(60), nullable=True)
    parent_code = Column(String(40), nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    sort = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (UniqueConstraint("kind", "code", name="uq_vehicle_catalog"),)
