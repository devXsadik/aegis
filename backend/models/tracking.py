"""Camera network graph and cross-camera tracks (chains of sightings of one target)."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.db.database import Base


class CameraEdge(Base):
    """Road link between two neighbouring cameras."""
    __tablename__ = "camera_edges"

    id = Column(Integer, primary_key=True, index=True)
    from_camera = Column(String(50), nullable=False, index=True)
    to_camera = Column(String(50), nullable=False, index=True)
    distance_m = Column(Float, nullable=False)
    travel_s = Column(Float, nullable=False)                # typical travel time
    bearing_deg = Column(Float, nullable=True)              # from → to
    road_name = Column(String(120), nullable=True)
    bidirectional = Column(Boolean, nullable=False, default=True, server_default="1")
    auto_suggested = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("from_camera", "to_camera", name="uq_camera_edge"),)


class CrossCameraTrack(Base):
    """One target followed across cameras; tied to one incident."""
    __tablename__ = "cross_camera_tracks"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(10), nullable=False)                 # vehicle | person
    target_ref = Column(String(40), nullable=False, index=True)
    incident_id = Column(Integer, nullable=True, index=True)
    status = Column(String(10), nullable=False, default="active", server_default="active", index=True)  # active|lost|closed
    verified = Column(Boolean, nullable=False, default=False, server_default="0")   # an operator confirmed it
    last_camera = Column(String(50), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True, index=True)
    direction = Column(String(4), nullable=True)
    bearing = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    hops = relationship("TrackHop", back_populates="track", cascade="all, delete-orphan", order_by="TrackHop.seen_at")


class TrackHop(Base):
    __tablename__ = "track_hops"

    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey("cross_camera_tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_id = Column(String(50), nullable=False)
    seen_at = Column(DateTime(timezone=True), nullable=False)
    direction = Column(String(4), nullable=True)
    bearing = Column(Float, nullable=True)
    method = Column(String(20), nullable=True)                # plate | attributes+reid | face | ...
    confidence = Column(Float, nullable=True)
    detection_id = Column(Integer, nullable=True)
    alert_id = Column(Integer, nullable=True)
    bolo_ref = Column(String(20), nullable=True)              # lookout that predicted this camera
    consistent = Column(Boolean, nullable=False, default=True, server_default="1")   # travel time plausible
    note = Column(Text, nullable=True)

    track = relationship("CrossCameraTrack", back_populates="hops")


class Notification(Base):
    """A message to one user (officer / operator): in-app, push, SMS. Acknowledged by them."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(24), nullable=False)          # target_detected | heading_to_area | assigned | escalation | lost
    priority = Column(String(10), nullable=False, default="high")
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    payload = Column(Text, nullable=True)              # JSON: camera, direction, eta, snapshot, map
    incident_id = Column(Integer, nullable=True, index=True)
    alert_id = Column(Integer, nullable=True, index=True)
    channels = Column(String(60), nullable=True)
    dedup_key = Column(String(120), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    ack_state = Column(String(14), nullable=True)      # acknowledged | en_route | located | unable
    acked_at = Column(DateTime(timezone=True), nullable=True)
    ack_deadline = Column(DateTime(timezone=True), nullable=True, index=True)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
