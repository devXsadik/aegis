from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Index
from sqlalchemy.sql import func
from backend.db.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    uri = Column(String(500), nullable=False)
    location = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    active = Column(Boolean, default=True)
    ptz_supported = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_camera_location", "location"),
    )
