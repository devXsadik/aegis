# AGENTS.md

## Running the system

```bash
# Run setup (install deps, create DB, migrate data)
./setup_phase1.sh

# Start FastAPI backend (auth, audit, DB)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Run surveillance with PostgreSQL backend
python main.py

# Run on video file
python main.py --video path/to/video.mp4
```

## Architecture facts

- **Phase 1**: FastAPI + PostgreSQL backend with JWT auth, audit logs, encryption.
- **Entrypoint**: `main_phase1.py` → uses `core/face_recognizer_db.py` and `utils/evidence_db.py` for DB integration.
- **Backend API**: `backend/` — FastAPI app with routes for auth, faces, evidence, audit.
- **Config**: `config/config.yaml` (camera source, model paths, thresholds).
- **Environment**: `.env` file (see `.env.example`) — contains DB URL, secret keys, encryption key.
- **Models**: YOLOv8 weights in `models/` (gitignored). `weapon_yolo.pt` required for weapon detection.
- **Face encodings**: Now stored in PostgreSQL `face_encodings` table (migrated from `face_encodings.pkl`).
- **Evidence**: Saved to `evidence/` directory with metadata in PostgreSQL `evidence` table. Supports encryption via `ENCRYPTION_KEY`.
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
