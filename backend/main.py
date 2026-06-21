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
from backend.middleware.rate_limiter import RateLimitMiddleware

logger = logging.getLogger("HumanAnalysis")

# ---------------------------------------------------------------------------
# Security: Validate critical secrets on startup
# ---------------------------------------------------------------------------
_INSECURE_DEFAULTS = {
    "change-me-in-production",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_64_CHARS_MIN",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_32_CHARS_MIN",
    "",
}


def _validate_secrets():
    """Warn (dev) or refuse to start (prod) with default secrets."""
    secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
    encryption_key = os.getenv("ENCRYPTION_KEY", "default-key-change-in-prod")
    env = os.getenv("ENVIRONMENT", "development")

    warnings = []
    if secret_key in _INSECURE_DEFAULTS:
        warnings.append("SECRET_KEY is using an insecure default value")
    if encryption_key in {"default-key-change-in-prod", "CHANGE_THIS_ENCRYPTION_KEY_32_CHARS", ""}:
        warnings.append("ENCRYPTION_KEY is using an insecure default value")

    for w in warnings:
        if env == "production":
            raise RuntimeError(f"SECURITY ERROR: {w}. Set a strong value in .env before running in production.")
        logger.warning(f"⚠️  SECURITY WARNING: {w}. Set a strong value in .env before deploying.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AI Smart Surveillance System API",
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
