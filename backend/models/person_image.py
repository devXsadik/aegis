"""
Person Images Model
Stores multiple images for each known person — images stored as bytes in DB
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, LargeBinary
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from backend.db.database import Base


class PersonImage(Base):
    __tablename__ = "person_images"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("known_persons.id"), nullable=False, index=True)
    image_path = Column(String(255), nullable=True)   # kept for legacy; no longer required
    image_data = Column(LargeBinary, nullable=True)   # raw JPEG bytes stored in DB
    image_type = Column(String(20), default="face")   # face, full_body, etc.
    filename = Column(String(255), nullable=True)      # original filename for reference
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    person = relationship("KnownPerson", back_populates="images")

    __table_args__ = (
        Index("idx_person_images_person_id", "person_id"),
    )
