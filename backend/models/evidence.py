from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from backend.db.database import Base


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    camera_location = Column(String(50), nullable=False, index=True)
    track_id = Column(Integer, nullable=False, index=True)
    person_name = Column(String(100), nullable=True)
    is_criminal = Column(Boolean, default=False)
    weapon_present = Column(Boolean, default=False)
    is_suspicious = Column(Boolean, default=False)
    reasons = Column(Text, nullable=True)
    frame_path = Column(String(255), nullable=True)
    roi_path = Column(String(255), nullable=True)
    encrypted = Column(Boolean, default=False)
    created_by = Column(String(50), nullable=True)
    category = Column(String(20), nullable=False, index=True)

    __table_args__ = (
        Index("idx_timestamp_location", "timestamp", "camera_location"),
        Index("idx_track_time", "track_id", "timestamp"),
    )
