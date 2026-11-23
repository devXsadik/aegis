import asyncio
import contextlib
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.db.database import init_db
from backend.api import alert_routes, audit_routes, events_routes, map_routes, vehicle_routes
from backend.api.auth_routes import router as auth_router
from backend.api.face_routes import router as face_router
from backend.api.evidence_routes import router as evidence_router
from backend.api.camera_routes import router as camera_router
from backend.api.analytics_routes import router as analytics_router
from backend.api.ws_routes import router as ws_router
from backend.api.jurisdiction_routes import router as jurisdiction_router
from backend.api.watchlist_routes import router as watchlist_router
from backend.api.ingest_routes import router as ingest_router
from backend.api.camera_registry_routes import router as camera_registry_router
from backend.api.detection_routes import router as detection_router
from backend.api.lookout_routes import router as lookout_router
from backend.api.tracking_routes import router as tracking_router
from backend.api.case_evidence_routes import router as case_evidence_router
from backend.api.governance_routes import router as governance_router
from backend.api.ml_routes import router as ml_router
from backend.api.dispatch_routes import router as dispatch_router
import backend.services.matching  # noqa: E402,F401  (registers the matchers with the event router)
from backend.api.system_routes import router as system_router
from backend.api.report_routes import router as report_router
from backend.api.stream_routes import router as stream_router
from backend.api.incident_routes import router as incident_router
from backend.api.custody_routes import router as custody_router
from backend.api.recording_routes import router as recording_router
from backend.api.reid_routes import router as reid_router
from backend.api.integration_routes import router as integration_router
from backend.api.calibration_routes import router as calibration_router
from backend.api.vms_routes import router as vms_router
from backend.api.config_routes import router as config_router
from backend.api.metrics_routes import router as metrics_router
from backend.api.capture_routes import router as capture_router
from backend.api.shift_routes import router as shift_router
from backend.api.responder_routes import router as responder_router
from backend.middleware.rate_limiter import RateLimitMiddleware

logger = logging.getLogger("HumanAnalysis")

# ---------------------------------------------------------------------------
# Security: Validate critical secrets on startup
# ---------------------------------------------------------------------------
_INSECURE_DEFAULTS = {
    "change-me-in-production",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_64_CHARS_MIN",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_32_CHARS_MIN",
    "CHANGE_THIS_ENCRYPTION_KEY_32_CHARS",
    "",
}


def _is_insecure(value, extra=None):
    if not value:
        return True
    if value in _INSECURE_DEFAULTS or (extra and value in extra):
        return True
    return value.startswith("CHANGE_THIS")


def _validate_secrets():
    """Refuse to start with missing/default secrets (all environments)."""
    from backend.auth.guards import internal_key_is_secure

    secret_key = os.getenv("SECRET_KEY", "")
    encryption_key = os.getenv("ENCRYPTION_KEY", "")
    salt = os.getenv("ENCRYPTION_SALT", "")

    problems = []
    if _is_insecure(secret_key) or len(secret_key) < 32:
        problems.append("SECRET_KEY missing, default, or shorter than 32 chars")
    if _is_insecure(encryption_key, {"default-key-change-in-prod"}):
        problems.append("ENCRYPTION_KEY missing or default")
    if _is_insecure(salt, {"default-salt"}):
        problems.append("ENCRYPTION_SALT missing or default")
    if not internal_key_is_secure():
        problems.append("INTERNAL_API_KEY missing or default")

    if problems:
        raise RuntimeError(
            "SECURITY ERROR: " + "; ".join(problems)
            + ". Run scripts/ensure_local_env.py or set strong values in .env."
        )


def _production_checks() -> list:
    """Settings a real deployment should have. Logged at start-up (not fatal: a pilot on one
    machine may knowingly skip some) and shown in Settings → System."""
    if os.getenv("ENVIRONMENT") != "production":
        return []
    from backend.auth.auth import COOKIE_SECURE
    from backend.services import blobstore
    db_url = os.getenv("DATABASE_URL", "")
    checks = [
        (COOKIE_SECURE, "COOKIE_SECURE is off: serve the dashboard over HTTPS and set it"),
        (not db_url.startswith("sqlite") and os.getenv("USE_SQLITE", "false").lower() != "true",
         "SQLite in production: use PostgreSQL"),
        (bool(os.getenv("REDIS_URL")), "No REDIS_URL: one API worker only, no fail-over"),
        (blobstore.backend() == "s3", "Evidence on this server's disk: set EVIDENCE_STORE=s3"),
        (bool(os.getenv("BACKUP_S3_BUCKET")), "Backups stay on this machine: set BACKUP_S3_BUCKET"),
        (bool(os.getenv("SENTRY_DSN")) or bool(os.getenv("METRICS_TOKEN")), "No error tracking or metrics token"),
        (os.getenv("MFA_REQUIRED", "false").lower() == "true", "Two-step sign-in not required (MFA_REQUIRED)"),
    ]
    return [msg for ok, msg in checks if not ok]


def _warn_if_multi_worker():
    """Without Redis, live frames, pipeline status, WebSocket clients and rate limits live in this
    process: with several workers each would see only part of them (a camera "offline" on one,
    alerts missing on another). With REDIS_URL they are shared (backend/services/cluster.py)."""
    from backend.services import cluster
    workers = int(os.getenv("WEB_CONCURRENCY", "1") or 1)
    if workers > 1 and not cluster.enabled():
        logger.error(f"WEB_CONCURRENCY={workers}: Aegis keeps live state in-process and needs exactly "
                     "one API worker. Run uvicorn with --workers 1, or set REDIS_URL.")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_secrets()
    _warn_if_multi_worker()
    for msg in _production_checks():
        logger.warning(f"Production check: {msg}")
    from backend.services import cluster
    from scripts.seed_cameras import seed_cameras
    with cluster.startup_lock():           # several workers start together: one at a time here
        init_db()
        seed_cameras()
    from backend.services.escalation import escalation_loop
    from backend.services.maintenance import health_watch_loop, maintenance_loop
    from backend.services.tracking_loop import tracking_loop
    cluster.start_subscriber(asyncio.get_running_loop())
    # With Redis and several workers, each job runs on exactly one of them (it moves if that dies).
    escalation_task = asyncio.create_task(cluster.run_as_leader("escalation", escalation_loop))
    background = [asyncio.create_task(cluster.run_as_leader(n, f)) for n, f in
                  (("maintenance", maintenance_loop), ("health-watch", health_watch_loop), ("tracking", tracking_loop))]
    try:
        from utils.config import load_yaml, expand_env
        from utils.alerts.event_publisher import set_auto_alerts_enabled
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml")
        if os.path.exists(cfg_path):
            cfg = expand_env(load_yaml(cfg_path))
            if "auto_alerts_enabled" in cfg:
                set_auto_alerts_enabled(bool(cfg.get("auto_alerts_enabled", True)))
    except Exception as e:
        logger.warning(f"Config auto_alerts load skipped: {e}")
    logger.info("✅ AI-SSS Backend started successfully")
    yield
    cluster.stop_subscriber()
    for task in (escalation_task, *background):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    lifespan=lifespan,
    title="Aegis — AI Smart Surveillance API",
    description="Intelligent surveillance platform with face recognition, ANPR, "
                "anomaly detection, cross-camera tracking, and analytics.",
    version="5.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)
from backend.observability import RequestContextMiddleware, configure_logging, init_sentry  # noqa: E402
configure_logging()
init_sentry()
app.add_middleware(RequestContextMiddleware)     # outermost: ids and latency cover everything

# ---------------------------------------------------------------------------
# Routes (prefixed under /api/v1 for versioning)
# ---------------------------------------------------------------------------
API_V1 = "/api/v1"

app.include_router(auth_router, prefix=API_V1)
app.include_router(face_router, prefix=API_V1)
app.include_router(evidence_router, prefix=API_V1)
app.include_router(audit_routes.router, prefix=API_V1)
app.include_router(camera_registry_router, prefix=API_V1)
app.include_router(camera_router, prefix=API_V1)
app.include_router(vehicle_routes.router, prefix=API_V1)
app.include_router(analytics_router, prefix=API_V1)
app.include_router(alert_routes.router, prefix=API_V1)
app.include_router(events_routes.router, prefix=API_V1)
app.include_router(map_routes.router, prefix=API_V1)
app.include_router(ws_router, prefix=API_V1)
app.include_router(system_router, prefix=API_V1)
app.include_router(report_router, prefix=API_V1)
app.include_router(stream_router, prefix=API_V1)
app.include_router(incident_router, prefix=API_V1)
app.include_router(custody_router, prefix=API_V1)
app.include_router(recording_router, prefix=API_V1)
app.include_router(reid_router, prefix=API_V1)
app.include_router(integration_router, prefix=API_V1)
app.include_router(calibration_router, prefix=API_V1)
app.include_router(vms_router, prefix=API_V1)
app.include_router(config_router, prefix=API_V1)
app.include_router(metrics_router, prefix=API_V1)
app.include_router(capture_router, prefix=API_V1)
app.include_router(shift_router, prefix=API_V1)
app.include_router(responder_router, prefix=API_V1)
app.include_router(jurisdiction_router, prefix=API_V1)
app.include_router(watchlist_router, prefix=API_V1)
app.include_router(ingest_router, prefix=API_V1)
app.include_router(detection_router, prefix=API_V1)
app.include_router(lookout_router, prefix=API_V1)
app.include_router(tracking_router, prefix=API_V1)
app.include_router(case_evidence_router, prefix=API_V1)
app.include_router(governance_router, prefix=API_V1)
app.include_router(ml_router, prefix=API_V1)
app.include_router(dispatch_router, prefix=API_V1)


@app.get("/health")
def health_check():
    checks = {"database": "unknown", "redis": "unknown", "pipeline": "unknown"}
    status = "healthy"
    try:
        from backend.db.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = str(e)
        status = "degraded"
    try:
        from backend.services.ha import redis_health
        rh = redis_health()
        # Redis is optional: without REDIS_URL the backend runs single-node, which is healthy.
        checks["redis"] = "ok" if rh["connected"] else ("down" if rh["enabled"] else "disabled")
        if checks["redis"] == "down":
            status = "degraded"
    except Exception as e:
        checks["redis"] = str(e)
    try:
        from backend.api.system_routes import pipeline_status
        _pipeline_status = pipeline_status()
        checks["pipeline"] = "online" if _pipeline_status.get("online") else "standby"
        if _pipeline_status.get("last_heartbeat"):
            checks["last_heartbeat"] = _pipeline_status["last_heartbeat"]
    except Exception:
        checks["pipeline"] = "unknown"
    from backend.services.model_health import model_status
    models = model_status()
    checks["models"] = models
    if any(v == "missing" for v in models.values()):
        status = "degraded"
    return {"status": status, "version": "5.0.0", "checks": checks}







