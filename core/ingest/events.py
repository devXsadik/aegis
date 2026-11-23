"""The one internal event format. Our own pipeline (cameras that only stream video) and AI
cameras that send their own face / plate / vehicle events (webhooks, SDKs) both produce it.

    {camera_id, timestamp, type: face|vehicle, crop_image, full_frame_ref, bbox, embedding,
     plate_text, vehicle_type, color, make_model, attribute_confidences, track_id}

`crop_image` is base64 JPEG on the wire (small); full frames go to object storage and travel as
`full_frame_ref`. Embeddings travel as base64 float32."""

from __future__ import annotations

import base64
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

TYPES = ("face", "vehicle", "person")


class EventError(ValueError):
    pass


def _ts(v) -> str:
    if v is None:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e12 else v, tz=timezone.utc).replace(tzinfo=None).isoformat()
    if isinstance(v, datetime):
        return (v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v).isoformat()
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise EventError(f"Bad timestamp: {v!r}")
    return (d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d).isoformat()


def encode_vec(vec) -> Optional[str]:
    if vec is None:
        return None
    return base64.b64encode(np.asarray(vec, dtype=np.float32).tobytes()).decode()


def decode_vec(s: Optional[str]) -> Optional[np.ndarray]:
    if not s:
        return None
    return np.frombuffer(base64.b64decode(s), dtype=np.float32)


@dataclass
class NormalizedEvent:
    camera_id: str
    type: str
    timestamp: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = "pipeline"                    # pipeline | webhook:<vendor> | sdk:<vendor> | simulator
    track_id: Optional[str] = None
    bbox: Optional[List[float]] = None          # [x, y, w, h] as fractions of the frame
    crop_image: Optional[str] = None            # base64 JPEG
    full_frame_ref: Optional[str] = None        # object-storage key / URL
    embedding: Optional[str] = None             # base64 float32
    embedding_model: Optional[str] = None
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    vehicle_type: Optional[str] = None
    color: Optional[str] = None
    color_secondary: Optional[str] = None
    make_model: Optional[str] = None
    attribute_confidences: Dict[str, float] = field(default_factory=dict)
    is_night: Optional[bool] = None             # IR / grayscale frame: colour unreliable
    direction: Optional[str] = None             # N … NW when the source knows it
    quality: Optional[float] = None             # 0–1 face / plate quality, when known
    extra: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if not self.camera_id or not str(self.camera_id).strip():
            raise EventError("camera_id is required")
        if self.type not in TYPES:
            raise EventError(f"type must be one of {TYPES}")
        self.timestamp = _ts(self.timestamp or None)
        if self.bbox is not None:
            if len(self.bbox) != 4 or not all(isinstance(x, (int, float)) for x in self.bbox):
                raise EventError("bbox must be [x, y, w, h]")
            if any(x > 1.0 for x in self.bbox):   # pixels? keep, mark as such
                self.extra["bbox_pixels"] = True
        for k, v in list(self.attribute_confidences.items()):
            try:
                self.attribute_confidences[k] = max(0.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                raise EventError(f"attribute_confidences[{k}] must be a number")
        if self.crop_image and len(self.crop_image) > 2_000_000:
            raise EventError("crop_image too large (send the frame to storage and pass full_frame_ref)")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NormalizedEvent":
        known = {f for f in cls.__dataclass_fields__}
        extra = {k: v for k, v in d.items() if k not in known}
        ev = cls(**{k: v for k, v in d.items() if k in known})
        ev.extra.update(extra)
        return ev

    def vector(self) -> Optional[np.ndarray]:
        return decode_vec(self.embedding)
