"""Dispatch ↔ field: messages on an incident, and the officers' duty roster."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from backend.db.database import Base


class IncidentMessage(Base):
    """Two-way thread between the command centre and the officers on an incident. Separate from
    case notes (internal analysis); every message is also on the incident timeline."""
    __tablename__ = "incident_messages"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(100), nullable=False)
    author_role = Column(String(20), nullable=False)
    body = Column(Text, nullable=False)
    evidence_ref = Column(String(40), nullable=True)     # a photo sent from the field (case evidence)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class OfficerShift(Base):
    """A planned duty period. Officers on shift now come first in the officer picker; the roster
    also answers "who covers Gulshan tonight"."""
    __tablename__ = "officer_shifts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ends_at = Column(DateTime(timezone=True), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="SET NULL"), nullable=True, index=True)
    assignment = Column(String(80), nullable=True)       # e.g. "Patrol car 3", "Gulshan-2 checkpoint"
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
