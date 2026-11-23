"""Every normalized face / vehicle / person event that reached the server.

Kept only for DETECTION_RETENTION_DAYS (expires_at; services/event_router.purge_expired), unless
attached to an incident. Face embeddings of people NOT on the watchlist are never stored here:
the face handler discards them after matching (Phase 8)."""

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, LargeBinary, String, Text
from sqlalchemy.sql import func

from backend.db.database import Base


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(40), unique=True, nullable=False, index=True)
    camera_id = Column(String(50), nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False, index=True)
    kind = Column(String(10), nullable=False, index=True)            # face | vehicle | person
    source = Column(String(40), nullable=True)
    track_id = Column(String(40), nullable=True, index=True)
    bbox = Column(String(80), nullable=True)                          # JSON [x, y, w, h]
    crop = Column(LargeBinary, nullable=True)                         # JPEG, sealed at rest
    crop_encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
    full_frame_ref = Column(String(255), nullable=True)
    plate_raw = Column(String(60), nullable=True)
    plate_canonical = Column(String(60), nullable=True, index=True)
    plate_confidence = Column(Float, nullable=True)
    vehicle_type = Column(String(30), nullable=True, index=True)
    color = Column(String(20), nullable=True, index=True)
    color_secondary = Column(String(20), nullable=True)
    make_model = Column(String(60), nullable=True, index=True)
    attr_conf = Column(Text, nullable=True)                           # JSON {plate, type, color, model, ...}
    color_reliable = Column(Boolean, nullable=False, default=True, server_default="1")
    direction = Column(String(4), nullable=True)
    embedding = Column(LargeBinary, nullable=True)                    # vehicle re-ID / matched face only
    embedding_model = Column(String(40), nullable=True)
    matched = Column(Boolean, nullable=False, default=False, server_default="0", index=True)
    match_ref = Column(String(40), nullable=True)                     # watchlist ref / person_id
    alert_id = Column(Integer, nullable=True)
    incident_id = Column(Integer, nullable=True, index=True)          # attached → kept past retention
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_detection_cam_ts", "camera_id", "ts"),)
