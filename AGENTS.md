# AGENTS.md

## Running the system

```bash
# Run setup (install deps, create DB, migrate data)
./setup_phase1.sh

# Start FastAPI backend (auth, audit, DB, WebSockets, cameras, vehicles)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Run surveillance with Pipeline Architecture
python main.py

# Run on video file
python main.py --video path/to/video.mp4
```

## Architecture facts

- **Phase 5**: Production Architecture with pipeline-based CV processing.
- **Entrypoint**: `main.py` → builds `SurveillancePipeline` from `core/pipeline/` stages.
- **Pipeline stages**: Detection → Tracking → Recognition → Behavior → Analytics → Output
- **Pipeline framework**: `core/pipeline/base.py` — `FrameContext` (data carrier), `PipelineStage` (abstract base with timing), `SurveillancePipeline` (orchestrator).
- **Pipeline stages**: `core/pipeline/stages/` — `detection.py`, `tracking.py`, `recognition.py`, `behavior.py`, `analytics.py`, `output.py`.
- **Visualization**: `core/visualization/hud.py` — all HUD drawing extracted from main.py.
- **Backend API**: `backend/` — FastAPI app with routes prefixed under `/api/v1/`. Includes CORS middleware, rate limiting, startup secret validation.
- **Config**: `config/config.yaml` (main config), `config/cameras.yaml` (multi-camera), `config/models.yaml` (model registry).
- **Environment**: `.env` file (see `.env.example`) — contains DB URL, secret keys, encryption key, webhook URLs. Docker-compose references `.env` (no hardcoded passwords).
- **Models**: YOLOv8 weights in `models/` (gitignored). `weapon_yolo.pt` for weapons, `yolov8l.pt` for vehicles.
- **Face encodings**: Stored in PostgreSQL `face_encodings` table, cached in `FaceRecognizerDB`.
- **Evidence**: Saved to `evidence/` directory with metadata in PostgreSQL. Supports AES-256 encryption.
- **ANPR**: License plate recognition using EasyOCR (`core/anpr.py`). Integrated into BehaviorStage.
- **Vehicle Detection**: YOLO-based vehicle detection with tracking (`core/vehicle_detector.py`).
- **Alert Orchestration**: Sends alerts via webhooks (`utils/alerts.py`). Dispatched from OutputStage.
- **Cross-Camera Tracking**: Person re-identification module (`core/cross_camera_tracker.py`).
- **Anomaly Detection**: Zone-based crowd and dwell anomalies (`core/anomaly_detector.py`). Integrated into BehaviorStage.
- **Analytics**: Heatmaps, dwell time, traffic flow (`core/analytics.py`). Integrated into AnalyticsStage.
- **Report Generation**: Incident reports and evidence bundles (`utils/reports.py`).
- **Logging**: Structured logging with file rotation (`utils/logger.py`).
- **Tests**: `tests/unit/` — pipeline, behavior, anomaly. Run with `pytest`.
- **Alarm**: MacOS-only — uses `afplay`.

## Directory conventions

- `known_person/` — one subdirectory per person, named `CRIMINAL_XXX_Name`, filled with face images.
- `core/` — CV modules. `face_recognizer_db.py` is the DB-backed version.
- `core/pipeline/` — Pipeline framework and stages.
- `core/visualization/` — HUD rendering and display code.
- `backend/` — FastAPI app: `api/` (routes), `models/` (SQLAlchemy), `db/` (database), `auth/` (JWT), `utils/` (encryption, audit), `middleware/` (rate limiting).
- `utils/` — logger config, `evidence_db.py` for DB-backed evidence saving, `alerts.py` for webhooks.
- `config/` — YAML configuration files (main, cameras, models).
- `tests/` — pytest test suite organized by type (unit, integration, e2e).

## Quirks

- `rerecognize_every: 30` in `config/config.yaml` — face re-recognition interval (frames per track ID).
- Throttled evidence: configurable via `evidence_throttle_seconds` (default 10s per track ID).
- PostgreSQL required — uses `pgvector` extension for face encoding storage.
- Encryption: set `ENCRYPTION_KEY` in `.env` to enable evidence file encryption (AES-256).
- Audit logs: all evidence saves and auth events logged to `audit_logs` table.
- API docs: available at `http://localhost:8000/docs` when backend is running.
- All API routes prefixed with `/api/v1/`.
- CORS enabled — configure `CORS_ORIGINS` in `.env`.
- Secret validation: backend warns on default secrets in dev, refuses to start in production.
- Pipeline stats: press `S` key during surveillance to print per-stage timing.
- Thermal mode: press `T` key to toggle thermal camera view.
