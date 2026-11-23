"""Training data and models: datasets (versioned), items + labels, the model registry, and the
review queue that collects operator corrections for the next training round."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.db.database import Base

TASKS = ("vehicle_detect", "vehicle_attr", "vehicle_reid", "face")
SPLITS = ("train", "val", "test")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False)
    task = Column(String(20), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(10), nullable=False, default="draft", server_default="draft")   # draft | frozen
    parent_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)
    classes = Column(Text, nullable=True)         # JSON snapshot of the class lists at freeze time
    split_seed = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    frozen_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship("DatasetItem", back_populates="dataset", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("name", "version", name="uq_dataset_version"),)


class DatasetItem(Base):
    __tablename__ = "dataset_items"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(400), nullable=False)           # image file under DATASETS_DIR
    sha256 = Column(String(64), nullable=False, index=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    split = Column(String(5), nullable=True, index=True)
    day_night = Column(String(5), nullable=True)          # day | night (IR / dark)
    source = Column(String(20), nullable=False, default="upload")    # upload | crop | review | detection
    labels = Column(Text, nullable=True)                  # JSON {vehicle_type, color, make_model, identity, boxes:[...]}
    labeled_by = Column(Integer, nullable=True)
    labeled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    dataset = relationship("Dataset", back_populates="items")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True)
    task = Column(String(20), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    version = Column(String(30), nullable=False)
    metrics = Column(Text, nullable=True)                 # JSON
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)
    artifact_path = Column(String(400), nullable=False)
    labels_path = Column(String(400), nullable=True)
    format = Column(String(10), nullable=False, default="onnx")      # onnx | pt | engine
    sha256 = Column(String(64), nullable=True)
    stage = Column(String(12), nullable=False, default="staging", server_default="staging", index=True)  # staging|production|archived
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    promoted_by = Column(Integer, nullable=True)
    promoted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("task", "version", name="uq_model_task_version"),)


class ReviewQueueItem(Base):
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(10), nullable=False)             # vehicle | face
    reason = Column(String(20), nullable=False)           # rejected_match | correction
    field = Column(String(20), nullable=True)             # color | vehicle_type | make_model | plate | identity
    predicted = Column(String(80), nullable=True)
    corrected = Column(String(80), nullable=True)
    note = Column(Text, nullable=True)
    alert_id = Column(Integer, nullable=True, index=True)
    detection_id = Column(Integer, nullable=True, index=True)
    crop = Column(LargeBinary, nullable=True)             # sealed JPEG
    crop_encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
    day_night = Column(String(5), nullable=True)
    score = Column(Float, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    status = Column(String(10), nullable=False, default="open", server_default="open", index=True)   # open | used | dismissed
    dataset_item_id = Column(Integer, nullable=True)
