import os
import yaml
import threading
import time
import json
import psutil
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from backend.db.database import init_db, SessionLocal
from backend.models.camera import Camera
from backend.api import (
    auth_routes, face_routes, evidence_routes, audit_routes,
    camera_routes, vehicle_routes, analytics_routes,
    alert_routes, config_routes, map_routes, events_routes,
)
from backend.middleware.rate_limiter import RateLimitMiddleware

app = FastAPI(
    title="AI Surveillance System API",
    description="Phase 4: Intelligence Layer with Analytics and Cross-Camera Tracking",
    version="4.0.0",
)

app.add_middleware(RateLimitMiddleware)

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
app.include_router(events_routes.router)

try:
    app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="dashboard")
except RuntimeError:
    pass


_start_time = time.time()


def _retention_worker():
    """Run evidence retention every 24 hours in background."""
    while True:
        try:
            time.sleep(86400)  # 24 hours
            from utils.retention import run_retention
            result = run_retention(dry_run=False)
            print(f"[retention] Auto-cleanup: {json.dumps(result)}")
        except Exception as e:
            print(f"[retention] Worker error: {e}")


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
    thread = threading.Thread(target=_retention_worker, daemon=True)
    thread.start()


@app.get("/health")
def health_check():
    return {"status": "healthy", "phase": "4 - Intelligence Layer"}


@app.get("/system/health")
def system_health(request: Request):
    import psutil
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    disk = psutil.disk_usage("/")
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return {
        "status": "healthy",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "cpu_percent": cpu,
        "memory_percent": mem.percent,
        "memory_used_mb": round(mem.used / 1024 / 1024, 1),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
        "python_version": __import__("sys").version,
    }
