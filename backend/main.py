import os
import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from backend.db.database import init_db, SessionLocal
from backend.models.camera import Camera
from backend.api import (
    auth_routes, face_routes, evidence_routes, audit_routes,
    camera_routes, vehicle_routes, analytics_routes,
    alert_routes, config_routes, map_routes,
)

app = FastAPI(
    title="AI Surveillance System API",
    description="Phase 4: Intelligence Layer with Analytics and Cross-Camera Tracking",
    version="4.0.0",
)

app.include_router(auth_routes.router)
app.include_router(face_routes.router)
app.include_router(evidence_routes.router)
app.include_router(audit_routes.router)
app.include_router(camera_routes.router)
app.include_router(vehicle_routes.router)
app.include_router(analytics_routes.router)
app.include_router(alert_routes.router)
app.include_router(config_routes.router)
app.include_router(map_routes.router)

try:
    app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="dashboard")
except RuntimeError:
    pass


def sync_cameras_from_config():
    """Load cameras from config.yaml into DB on startup."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "config.yaml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        return

    cameras_cfg = cfg.get("cameras", [])
    db = SessionLocal()
    try:
        for cam_cfg in cameras_cfg:
            cid = cam_cfg.get("id", "")
            if not cid:
                continue
            existing = db.query(Camera).filter(Camera.camera_id == cid).first()
            if existing:
                existing.uri = str(cam_cfg.get("uri", existing.uri))
                existing.location = cam_cfg.get("location", existing.location)
                existing.name = cam_cfg.get("name", existing.name)
                if cam_cfg.get("lat"):
                    existing.lat = cam_cfg["lat"]
                if cam_cfg.get("lng"):
                    existing.lng = cam_cfg["lng"]
            else:
                cam = Camera(
                    camera_id=cid,
                    name=cam_cfg.get("name", cid),
                    uri=str(cam_cfg.get("uri", "")),
                    location=cam_cfg.get("location", ""),
                    lat=cam_cfg.get("lat", 0.0),
                    lng=cam_cfg.get("lng", 0.0),
                    ptz_supported=cam_cfg.get("ptz_supported", False),
                )
                db.add(cam)
        db.commit()
    except Exception as e:
        print(f"Config sync error: {e}")
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    init_db()
    sync_cameras_from_config()


@app.get("/health")
def health_check():
    return {"status": "healthy", "phase": "4 - Intelligence Layer"}
