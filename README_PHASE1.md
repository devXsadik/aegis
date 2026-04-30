# AI Surveillance System - Phase 1 Security Foundation

## Overview
Enhanced surveillance system with PostgreSQL backend, JWT authentication, audit logging, and evidence encryption.

## Quick Start

```bash
# Run automated setup (PostgreSQL required)
./setup_phase1.sh

# Start FastAPI backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Run surveillance
python main_phase1.py
```

## Features Added in Phase 1

### Security
- **JWT Authentication** - Role-based access (admin, operator, viewer)
- **PostgreSQL Backend** - Replaces pickle/CSV with proper database
- **Evidence Encryption** - AES-256 encryption for sensitive evidence files
- **Audit Logging** - Immutable audit trail for all system actions

### Database Schema
- `users` - System users with role-based access
- `face_encodings` - Face recognition data (migrated from pickle)
- `evidence` - Detection events with metadata (migrated from CSV)
- `audit_logs` - System activity audit trail

### API Endpoints
- `POST /auth/login` - User login, returns JWT token
- `POST /auth/users` - Create new user (admin only)
- `GET /faces/` - List face encodings
- `POST /faces/encode` - Re-encode faces from known_person/
- `GET /evidence/` - List evidence records
- `GET /audit/` - View audit logs (admin only)

## Configuration

Copy `.env.example` to `.env` and configure:
- `DATABASE_URL` - PostgreSQL connection string
- `SECRET_KEY` - JWT signing key (generate secure random)
- `ENCRYPTION_KEY` - For evidence encryption (generate with Fernet)

## Migration from Legacy

The setup script automatically migrates:
- `face_encodings.pkl` → PostgreSQL `face_encodings` table
- `evidence/log.csv` → PostgreSQL `evidence` table

## API Documentation

Once backend is running, visit: `http://localhost:8000/docs`

## Project Structure

```
├── main_phase1.py          # Phase1 entrypoint (DB-backed)
├── main.py                 # Legacy entrypoint (pickle/CSV)
├── backend/                # FastAPI backend
│   ├── api/              # Route handlers
│   ├── models/           # SQLAlchemy models
│   ├── db/               # Database connection
│   ├── auth/             # JWT authentication
│   └── utils/            # Encryption, audit
├── core/                  # CV modules
├── config/                # YAML configuration
└── setup_phase1.sh       # Automated setup script
```
