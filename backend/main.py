import os
import logging

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
    """Warn (dev) or refuse to start (prod) with default secrets."""
    secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
    encryption_key = os.getenv("ENCRYPTION_KEY", "default-key-change-in-prod")
    env = os.getenv("ENVIRONMENT", "development")

    warnings = []
    if _is_insecure(secret_key):
        warnings.append("SECRET_KEY is using an insecure default value")
    if _is_insecure(encryption_key, {"default-key-change-in-prod"}):
        warnings.append("ENCRYPTION_KEY is using an insecure default value")

    for w in warnings:
        if env == "production":
            raise RuntimeError(f"SECURITY ERROR: {w}. Set a strong value in .env before running in production.")
        logger.warning(f"⚠️  SECURITY WARNING: {w}. Set a strong value in .env before deploying.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
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

# ---------------------------------------------------------------------------
# Routes (prefixed under /api/v1 for versioning)
# ---------------------------------------------------------------------------
API_V1 = "/api/v1"

app.include_router(auth_router, prefix=API_V1)
app.include_router(face_router, prefix=API_V1)
app.include_router(evidence_router, prefix=API_V1)
app.include_router(audit_routes.router, prefix=API_V1)
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


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    _validate_secrets()
    init_db()
    logger.info("✅ AI-SSS Backend started successfully")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "version": "5.0.0",
        "phase": "5 - Production Architecture",
    }






