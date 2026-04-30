from fastapi import FastAPI
from backend.db.database import init_db
from backend.api import auth_routes, face_routes, evidence_routes, audit_routes

app = FastAPI(
    title="AI Surveillance System API",
    description="Phase 1: Security Foundation",
    version="1.0.0"
)

app.include_router(auth_routes.router)
app.include_router(face_routes.router)
app.include_router(evidence_routes.router)
app.include_router(audit_routes.router)


@app.on_event("startup")
async def startup_event():
    init_db()


@app.get("/health")
def health_check():
    return {"status": "healthy", "phase": "1 - Security Foundation"}
