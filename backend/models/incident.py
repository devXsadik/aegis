"""Server-side incident tickets for national-security command workflows."""

from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Index, Float,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from backend.db.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(20), unique=True, nullable=False, index=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    incident_type = Column(String(40), nullable=False, default="ALERT", index=True)
    priority = Column(String(10), nullable=False, default="high", index=True)
    status = Column(String(20), nullable=False, default="new", index=True)   # services/incident_status.py
    source = Column(String(20), nullable=False, default="alert", server_default="alert")  # face_match|vehicle_match|manual|alert

    camera_id = Column(String(50), nullable=True, index=True)
    camera_location = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    person_name = Column(String(100), nullable=True)
    plate_number = Column(String(20), nullable=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="SET NULL"), nullable=True, index=True)
    watchlist_person_id = Column(Integer, nullable=True, index=True)    # known_persons.id
    watchlist_vehicle_id = Column(Integer, nullable=True, index=True)   # watchlist_vehicles.id
    cross_track_id = Column(Integer, nullable=True, index=True)         # cross_camera_tracks.id

    # Primary assignee (kept for older screens); every assignee is in incident_assignments.
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_name = Column(String(80), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String(80), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    notes = relationship("IncidentNote", back_populates="incident", cascade="all, delete-orphan")
    events = relationship("IncidentEvent", back_populates="incident", cascade="all, delete-orphan",
                          order_by="IncidentEvent.id")
    assignments = relationship("IncidentAssignment", back_populates="incident", cascade="all, delete-orphan",
                               order_by="IncidentAssignment.id")

    __table_args__ = (
        Index("idx_incident_status_priority", "status", "priority"),
        Index("idx_incident_camera", "camera_id", "created_at"),
    )


class IncidentNote(Base):
    __tablename__ = "incident_notes"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    author_id = Column(Integer, nullable=True)
    author_name = Column(String(80), nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="notes")


class IncidentEvent(Base):
    """Append-only timeline entry for an incident."""
    __tablename__ = "incident_events"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    message = Column(Text, nullable=False)
    actor = Column(String(80), nullable=True)
    actor_id = Column(Integer, nullable=True)
    camera_id = Column(String(50), nullable=True)
    payload = Column(Text, nullable=True)          # JSON: {from, to, officer_ids, evidence_id, ...}
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    incident = relationship("Incident", back_populates="events")


ASSIGNMENT_STATES = ("assigned", "acknowledged", "en_route", "on_scene", "located", "unable")


class IncidentAssignment(Base):
    """One officer on one incident. Many officers per incident."""
    __tablename__ = "incident_assignments"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by = Column(Integer, nullable=True)
    state = Column(String(14), nullable=False, default="assigned", server_default="assigned")
    out_of_area = Column(Boolean, nullable=False, default=False, server_default="0")   # neighbour override used
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    incident = relationship("Incident", back_populates="assignments")
    user = relationship("User")

    __table_args__ = (Index("uq_incident_assignment", "incident_id", "user_id", unique=True),)
