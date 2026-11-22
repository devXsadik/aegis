"""A building floor plan drawn on the operations map, stretched over a lat/lng box.

The image lives in the database (not a file) so the nightly backup carries it with the rest.
"""
from sqlalchemy import Column, DateTime, Float, Integer, LargeBinary, String
from sqlalchemy.sql import func

from backend.db.database import Base


class FloorPlan(Base):
    __tablename__ = "floor_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    image = Column(LargeBinary, nullable=False)
    content_type = Column(String(30), nullable=False, default="image/png")
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    south = Column(Float, nullable=False)
    west = Column(Float, nullable=False)
    north = Column(Float, nullable=False)
    east = Column(Float, nullable=False)
    opacity = Column(Float, nullable=False, default=0.75, server_default="0.75")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
