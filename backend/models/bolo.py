"""Lookouts (BOLO — Be On the Look Out): a target pushed to a set of cameras for a time window.

Created automatically when a tracked target leaves a camera (Phase 9: next likely cameras in the
direction of travel), or by an operator from Vehicle Search ("Start lookout" for an area).
Inside an active lookout, attribute-only vehicle matches ("Candidate vehicle") may alert."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.db.database import Base

BOLO_STATUSES = ("active", "reacquired", "expired", "lost", "cancelled")


class Bolo(Base):
    __tablename__ = "bolos"

    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String(20), unique=True, nullable=False, index=True)         # B-XXXXXXXX
    kind = Column(String(10), nullable=False)                                  # vehicle | person
    target_ref = Column(String(40), nullable=True, index=True)                 # watchlist ref / person_id
    payload = Column(Text, nullable=True)       # JSON: plate, type, colour, model, embeddings (base64)
    origin = Column(String(12), nullable=False, default="auto")               # auto (handoff) | manual (search)
    origin_camera = Column(String(50), nullable=True)
    direction = Column(String(4), nullable=True)                               # N … NW
    heading_deg = Column(Float, nullable=True)
    incident_id = Column(Integer, nullable=True, index=True)
    cross_track_id = Column(Integer, nullable=True, index=True)
    reason = Column(Text, nullable=True)
    case_no = Column(String(60), nullable=True)
    created_by = Column(Integer, nullable=True)
    ring = Column(Integer, nullable=False, default=1, server_default="1")
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(12), nullable=False, default="active", server_default="active", index=True)
    found_camera = Column(String(50), nullable=True)
    found_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cameras = relationship("BoloCamera", back_populates="bolo", cascade="all, delete-orphan")


class BoloCamera(Base):
    __tablename__ = "bolo_cameras"

    id = Column(Integer, primary_key=True)
    bolo_id = Column(Integer, ForeignKey("bolos.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_id = Column(String(50), nullable=False, index=True)
    rank = Column(Integer, nullable=False, default=0)
    ring = Column(Integer, nullable=False, default=1)
    eta_from_s = Column(Float, nullable=True)
    eta_to_s = Column(Float, nullable=True)
    distance_m = Column(Float, nullable=True)
    notified = Column(Boolean, nullable=False, default=False, server_default="0")

    bolo = relationship("Bolo", back_populates="cameras")
