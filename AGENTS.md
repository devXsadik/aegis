# AGENTS.md

## Running the system

```bash
# Run setup (install deps, create DB, migrate data)
./setup_phase1.sh

# Start FastAPI backend (auth, audit, DB, WebSockets, cameras, vehicles)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Run surveillance with Phase 3 features (ANPR, vehicle detection, alerts)
python main.py

# Run on video file
python main.py --video path/to/video.mp4
```

## Architecture facts

- **Phase 4**: Full system with intelligence layer - cross-camera tracking, anomaly detection, analytics, and report generation.
- **Entrypoint**: `main.py` → uses `core/` (face_recognizer_db, anpr, vehicle_detector, cross_camera_tracker, anomaly_detector, analytics) and `utils/` (evidence_db, alerts, websocket, reports).
- **Backend API**: `backend/` — FastAPI app with routes for auth, faces, evidence, audit, cameras, vehicles, analytics. Includes WebSocket support.
- **Config**: `config/config.yaml` (camera source, model paths, thresholds, criminal watchlist).
- **Environment**: `.env` file (see `.env.example`) — contains DB URL, secret keys, encryption key, webhook URLs.
- **Models**: YOLOv8 weights in `models/` (gitignored). `weapon_yolo.pt` required for weapon detection. `yolov8l.pt` used for vehicle detection.
- **Face encodings**: Stored in PostgreSQL `face_encodings` table.
- **Evidence**: Saved to `evidence/` directory with metadata in PostgreSQL `evidence` table. Supports encryption via `ENCRYPTION_KEY`.
- **ANPR**: License plate recognition using EasyOCR (`core/anpr.py`). Watchlisted plates stored in DB.
- **Vehicle Detection**: YOLO-based vehicle detection with tracking (`core/vehicle_detector.py`).
- **Alert Orchestration**: Sends alerts to law enforcement/emergency services via webhooks (`utils/alerts.py`).
- **Cross-Camera Tracking**: Re-identifies persons across multiple camera feeds (`core/cross_camera_tracker.py`).
- **Anomaly Detection**: Detects unusual patterns in surveillance data (`core/anomaly_detector.py`).
- **Analytics**: Heatmaps, dwell time analysis, movement patterns (`core/analytics.py`).
- **Report Generation**: Creates incident reports and evidence bundles (`utils/reports.py`).
- **Alarm**: MacOS-only — uses `afplay`.

## Directory conventions

- `known_person/` — one subdirectory per person, named `CRIMINAL_XXX_Name`, filled with face images.
- `core/` — CV modules. `face_recognizer_db.py` is the DB-backed version.
- `backend/` — FastAPI app: `api/` (routes), `models/` (SQLAlchemy), `db/` (database), `auth/` (JWT), `utils/` (encryption, audit).
- `utils/` — logger config, `evidence_db.py` for DB-backed evidence saving.

## Quirks

- `RERECOGNIZE_EVERY = 30` in `main_phase1.py` — face re-recognition interval (frames per track ID).
- Throttled evidence: max once per 10 seconds per track ID.
- PostgreSQL required — uses `pgvector` extension for face encoding storage.
- Encryption: set `ENCRYPTION_KEY` in `.env` to enable evidence file encryption (AES-256).
- Audit logs: all evidence saves and auth events logged to `audit_logs` table.
- API docs: available at `http://localhost:8000/docs` when backend is running.
- No tests, no lint, no typecheck configured yet.
