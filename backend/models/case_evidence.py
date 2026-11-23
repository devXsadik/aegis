"""Case evidence uploaded by officers (and alert snapshots attached by the system), its custody
chain, and evidence face grouping (one folder per person)."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.db.database import Base

KINDS = ("image", "video", "audio", "pdf", "snapshot", "other")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String(20), unique=True, nullable=False, index=True)        # EV-XXXXXXXX
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    kind = Column(String(10), nullable=False, index=True)
    description = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True, index=True)
    camera_id = Column(String(50), nullable=True)                           # system snapshots
    original_filename = Column(String(255), nullable=True)
    content_type = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)                 # of the ORIGINAL bytes
    storage_path = Column(String(400), nullable=False)                      # sealed file
    encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    parent_id = Column(Integer, ForeignKey("evidence_items.id"), nullable=True, index=True)   # earlier version
    source = Column(String(12), nullable=False, default="upload", server_default="upload")     # upload | system
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    device_info = Column(String(300), nullable=True)
    faces_status = Column(String(12), nullable=False, default="pending", server_default="pending")  # pending|processing|done|none|failed|skipped
    faces_found = Column(Integer, nullable=False, default=0, server_default="0")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(Integer, nullable=True)
    delete_reason = Column(Text, nullable=True)


class EvidenceItemCustody(Base):
    """Append-only, hash-chained per item: UPLOADED, VIEWED, DOWNLOADED, VERSIONED, DELETED, VERIFIED."""
    __tablename__ = "evidence_item_custody"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("evidence_items.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    actor = Column(String(80), nullable=False)
    actor_id = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=False)
    prev_hash = Column(String(64), nullable=True)
    record_hash = Column(String(64), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    at = Column(DateTime(timezone=True), nullable=False)


class PersonGroup(Base):
    __tablename__ = "person_groups"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)      # UNKNOWN-000123
    name = Column(String(120), nullable=True)
    status = Column(String(20), nullable=False, default="unknown", server_default="unknown")  # unknown|named|known|criminal_possible|criminal
    known_person_id = Column(Integer, ForeignKey("known_persons.id", ondelete="SET NULL"), nullable=True, index=True)
    best_face_id = Column(Integer, nullable=True)
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    merged_into = Column(Integer, nullable=True)                            # when merged away
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    faces = relationship("EvidenceFace", back_populates="group")


class EvidenceFace(Base):
    __tablename__ = "evidence_faces"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    frame_ts = Column(Float, nullable=True)                 # seconds into a video
    bbox = Column(String(80), nullable=True)
    crop = Column(LargeBinary, nullable=False)              # sealed JPEG
    crop_encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
    embedding = Column(LargeBinary, nullable=False)
    embedding_model = Column(String(40), nullable=False)
    quality = Column(Float, nullable=True)
    group_id = Column(Integer, ForeignKey("person_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    group_similarity = Column(Float, nullable=True)
    watch_person_id = Column(Integer, nullable=True, index=True)          # possible criminal match
    watch_similarity = Column(Float, nullable=True)
    verify_status = Column(String(10), nullable=True)                     # pending | confirmed | rejected
    verified_by = Column(Integer, nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    group = relationship("PersonGroup", back_populates="faces")


class GroupOperation(Base):
    """Merge / move / split / rename / link — who did what to which faces."""
    __tablename__ = "person_group_ops"

    id = Column(Integer, primary_key=True, index=True)
    op = Column(String(12), nullable=False)
    actor_id = Column(Integer, nullable=True)
    actor = Column(String(80), nullable=True)
    details = Column(Text, nullable=True)
    at = Column(DateTime(timezone=True), server_default=func.now())


class EvidencePerson(Base):
    """A person seen in a case's evidence file, with clothing colours, for "find the man in the red
    shirt" inside that case. Only evidence attached to an incident is indexed — never live video."""
    __tablename__ = "evidence_persons"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    t_seconds = Column(Float, nullable=True)                  # video offset; None for a photo
    bbox = Column(String(60), nullable=False)                 # x1,y1,x2,y2 in the frame
    upper_color = Column(String(12), nullable=True, index=True)
    lower_color = Column(String(12), nullable=True, index=True)
    crop = Column(LargeBinary, nullable=True)                 # small JPEG, sealed like the evidence
    crop_encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
