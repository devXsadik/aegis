"""Shift log: operator notes during a shift, and the handover to the next shift."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from backend.db.database import Base


class ShiftEntry(Base):
    __tablename__ = "shift_entries"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(50), nullable=False)
    kind = Column(String(12), nullable=False, default="note", index=True)   # note | handover
    camera_id = Column(String(50), nullable=True)                           # a note about one camera
    text = Column(Text, nullable=False, default="")
    summary = Column(Text, nullable=True)            # handover: JSON snapshot of the shift's numbers
    accepted_by = Column(String(50), nullable=True)  # handover: the operator who took over
    accepted_at = Column(DateTime(timezone=True), nullable=True)
