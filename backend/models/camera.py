from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, LargeBinary, Text
from sqlalchemy.sql import func
from backend.db.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    rtsp_url = Column(String(255), nullable=True)
    heading = Column(Float, nullable=True)     # degrees clockwise from north the camera faces (map field-of-view cone)
    fov = Column(Float, nullable=True)         # horizontal field of view, degrees
    range_m = Column(Float, nullable=True)     # how far it sees, metres
    active = Column(Boolean, default=True)
    jurisdiction_id = Column(Integer, nullable=True, index=True)   # thana; else found by point-in-polygon
    # Registry (Phase 5). Credentials are sealed at rest and never returned by the API.
    protocol = Column(String(12), nullable=False, default="rtsp", server_default="rtsp")  # rtsp|onvif|vendor|webhook|device|file
    vendor = Column(String(30), nullable=True)            # hikvision | dahua | uniview | generic …
    credentials = Column(LargeBinary, nullable=True)      # JSON {username, password}, sealed
    credentials_encrypted = Column(Boolean, nullable=False, default=False, server_default="0")
    address = Column(String(200), nullable=True)
    road_name = Column(String(120), nullable=True)
    capabilities = Column(Text, nullable=True)            # JSON list: face, anpr, vehicle_attr, ptz
    ir_mode = Column(Boolean, nullable=False, default=False, server_default="0")
    status = Column(String(10), nullable=False, default="unknown", server_default="unknown")  # online|degraded|offline|disabled|unknown
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    sample_fps = Column(Float, nullable=True)             # frames analysed per second (None = pipeline default)
    priority = Column(Integer, nullable=False, default=0, server_default="0")   # raised while on a lookout
    ingest_token_hash = Column(String(64), nullable=True)  # sha256 of the per-camera webhook token
    # JSON {zones: [...], lines: [...]} in normalized 0-1 coordinates (see core/analysis/zones.py)
    geometry = Column(Text, nullable=True)
    geometry_updated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
