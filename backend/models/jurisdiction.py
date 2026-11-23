"""Jurisdictions (division → district → thana → beat) and police officer profiles."""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.db.database import Base

LEVELS = ("division", "district", "thana", "beat")
DUTY_STATUSES = ("available", "on_duty", "busy", "off_duty")


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(40), unique=True, nullable=False, index=True)    # e.g. DHK-DMP-GULSHAN
    name_en = Column(String(100), nullable=False)
    name_bn = Column(String(100), nullable=True)
    level = Column(String(12), nullable=False, default="thana", index=True)
    parent_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="SET NULL"), nullable=True, index=True)
    geojson = Column(Text, nullable=True)          # Polygon / MultiPolygon, [lng, lat] order
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    parent = relationship("Jurisdiction", remote_side=[id])


class OfficerProfile(Base):
    """Police details for a `users` row with role police (or supervisor)."""
    __tablename__ = "officer_profiles"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    full_name = Column(String(100), nullable=True)
    rank = Column(String(40), nullable=True)                       # e.g. SI, ASI, Inspector
    badge_no = Column(String(30), unique=True, nullable=True, index=True)
    station_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="SET NULL"), nullable=True)  # thana
    duty_status = Column(String(12), nullable=False, default="off_duty", server_default="off_duty", index=True)
    photo = Column(LargeBinary, nullable=True)
    photo_type = Column(String(30), nullable=True)
    last_lat = Column(Float, nullable=True)
    last_lng = Column(Float, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    station = relationship("Jurisdiction")


class OfficerJurisdiction(Base):
    __tablename__ = "officer_jurisdictions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("user_id", "jurisdiction_id", name="uq_officer_jurisdiction"),)
