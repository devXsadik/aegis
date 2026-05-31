# AGENTS.md

## Running the system

```bash
# Full setup (PostgreSQL req'd): creates DB, .env, installs deps, migrates data
./setup_phase1.sh

# One-command launcher — starts backend + pipeline
./run.sh [--camera URL] [--video FILE] [--port PORT] [--ssl] [--no-backend] [--no-pipeline]

# Or separately:
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000       # FastAPI backend
python main.py [--camera URL] [--video FILE]                       # Surveillance pipeline

# Ingest face images from known_person/ into DB
python3 ingest_known_persons.py

# Database init (with seed admin user: admin/Admin123!)
python3 -m backend.init_db_all

# Migrate from legacy pickle/CSV to PostgreSQL
python3 -m backend.migrate

# Production deploy (Docker)
./deploy.sh                     # validates .env, builds, starts all services
docker-compose up -d            # or use compose directly
```

## Architecture

- **Monorepo**, single Python project. `PYTHONPATH=.` required when running modules directly (auto-set by `run.sh`).
- **`main.py`** — main surveillance pipeline: human detection/tracking, face recognition (DB-backed), weapon detection, ANPR (EasyOCR), vehicle detection (YOLO), cross-camera tracking, anomaly detection, analytics. All CV modules in `core/`.
- **`backend/`** — FastAPI app (Phase 4). Routes in `api/`, SQLAlchemy models in `models/`, JWT auth in `auth/`. Mounts static dashboard at `frontend/index.html`.
- **`config/config.yaml`** — single source of truth for cameras, model paths, thresholds, watchlist. Cross-camera tracking and analytics **disabled by default**.
- **`.env`** — `DATABASE_URL`, `SECRET_KEY`, `ENCRYPTION_KEY` (see `.env.example`). `ENCRYPTION_KEY` enables AES-256 evidence encryption.
- **PostgreSQL + pgvector** — face encodings stored in `face_encodings` table with vector search. Evidence metadata in `evidence` table. All events logged to `audit_logs`.
- **Models**: YOLOv8 weights in `models/` (gitignored). `weapon_yolo.pt` for weapons, `yolov8l.pt` for vehicles, `yolov8n.pt` (or `yolov8x.pt`) for humans.

## Security (recently added)

- **JWT_SECRET** loaded from `.env`, startup fails if unset or placeholder.
- **Brute-force protection**: 5 failed logins → account locked for 15 min.
- **Evidence encrypted at rest** via `EncryptionManager` (AES-256) when saved to DB.
- **Tamper-proof audit chain**: each `audit_logs` entry carries an HMAC-SHA256 hash of the previous entry. Verify with `AuditLogger.verify_chain()`.
- **HTTPS**: `./run.sh --ssl` generates self-signed certs and starts uvicorn with TLS.
- **Password policy**: minimum 8 chars, must include uppercase, lowercase, digit.
- **Password change + token refresh** endpoints at `POST /auth/change-password` and `POST /auth/refresh`.
- **Alerts enabled by default** (set `ALERTS_ENABLED=false` in `.env` to disable).

## Key quirks

- `RERECOGNIZE_EVERY = 90` in `main.py` — face re-recognition interval (frames per track ID). Line 34.
- Evidence saved at most once per 10 seconds per track ID.
- Alarm: macOS-only via `afplay`.
- **docker-compose** maps PostgreSQL to **5433** (not 5432), Redis to **6380** (not 6379).
- `known_person/` — one subdirectory per person, named `CRIMINAL_XXX_Name`. Run `ingest_known_persons.py` to load into DB.
- `init_db.py` creates minimal tables; `init_db_all.py` creates **all tables** + default admin user.
- API docs: `http://localhost:8000/docs` when backend is running.
- `simple_hud: true` in config.yaml avoids heavy HUD overlays (data stream, radar, crosshairs) for performance.
- Tests exist in `tests/` (uses `pytest`) but **pytest not in requirements** — install manually before running.

## Directory map

| Path | Purpose |
|------|---------|
| `main.py` | Surveillance pipeline entrypoint |
| `core/` | CV modules: detector, tracker, face recog, ANPR, vehicle, cross-camera, anomaly, analytics, stream manager |
| `backend/` | FastAPI app: `api/` (routes), `models/` (SQLAlchemy), `db/`, `auth/` (JWT), `utils/` (encryption, audit, websocket) |
| `utils/` | Shared: logger, evidence_db, alerts, reports, performance, camera_discovery, retention |
| `config/` | `config.yaml` — all settings |
| `frontend/` | Static dashboard (`index.html`) |
| `known_person/` | Face images per person directory |
| `evidence/` | Saved evidence files (gitignored) |
| `models/` | YOLOv8 weights (gitignored) |
| `tests/` | pytest tests (pytest not in requirements.txt) |
