from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, Index
from sqlalchemy.sql import func
from backend.db.database import Base
import numpy as np


class FaceEncoding(Base):
    __tablename__ = "face_encodings"

    id = Column(Integer, primary_key=True, index=True)
    person_name = Column(String(100), nullable=False, index=True)
    person_id = Column(String(50), nullable=False, index=True)
    encoding = Column(LargeBinary, nullable=False)
    image_path = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_person_name", "person_name"),
        Index("idx_person_id", "person_id"),
    )

    @staticmethod
    def serialize_encoding(encoding: np.ndarray) -> bytes:
        return encoding.tobytes()

    @staticmethod
    def deserialize_encoding(data: bytes) -> np.ndarray:
        return np.frombuffer(data, dtype=np.float64)
