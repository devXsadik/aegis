"""
Database engine — PostgreSQL (prod/Render) or SQLite (local zero-setup).

If DATABASE_URL points at unreachable local Postgres, falls back to
data/ai_sss.db so `./run.sh` works without Docker/psql installed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

logger = logging.getLogger("HumanAnalysis")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = "sqlite:///" + (ROOT / "data" / "ai_sss.db").as_posix()


def _normalize_database_url(url: str) -> str:
    """Render and other cloud Postgres providers require SSL."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    if url.startswith("sqlite:"):
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    host = (parsed.hostname or "").lower()
    needs_ssl = host.endswith(".render.com") or os.getenv("DATABASE_SSL", "").lower() in {"1", "true", "yes"}
    if needs_ssl and "sslmode" not in query:
        query["sslmode"] = "require"

    if query:
        url = urlunparse(parsed._replace(query=urlencode(query)))
    elif needs_ssl:
        url = f"{url}?sslmode=require"

    return url


def _is_local_postgres(url: str) -> bool:
    if not url.startswith("postgresql"):
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", ""}


def _can_connect(url: str) -> bool:
    try:
        args = {}
        kwargs = {}
        if url.startswith("sqlite"):
            args["check_same_thread"] = False
        else:
            if "sslmode=require" in url:
                args["sslmode"] = "require"
            kwargs["pool_pre_ping"] = True
        eng = create_engine(url, connect_args=args, **kwargs)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


def _resolve_database_url() -> str:
    force_sqlite = os.getenv("USE_SQLITE", "").lower() in {"1", "true", "yes"}
    raw = os.getenv("DATABASE_URL", "").strip()

    if force_sqlite or not raw:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        return DEFAULT_SQLITE

    url = _normalize_database_url(raw)

    if url.startswith("sqlite"):
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        return url

    if _can_connect(url):
        return url

    # Local Postgres missing (role/db not created, Docker down) → SQLite
    if _is_local_postgres(url) or os.getenv("ALLOW_SQLITE_FALLBACK", "true").lower() in {"1", "true", "yes"}:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Database unreachable (%s) — falling back to SQLite at data/ai_sss.db",
            urlparse(url).hostname or url[:40],
        )
        return DEFAULT_SQLITE

    return url


DATABASE_URL = _resolve_database_url()

_connect_args = {}
_engine_kwargs = {"pool_pre_ping": True}

if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
    # SQLite does not support pool_size / max_overflow the same way
    engine = create_engine(
        DATABASE_URL,
        connect_args={**_connect_args, "timeout": 30},
        pool_pre_ping=True,
        # One file, many threads: SQLite serialises writes itself. A larger pool keeps async
        # routes (which take their connection on the event loop) from waiting on worker threads
        # that are in turn waiting on the loop for a live broadcast.
        pool_size=int(os.getenv("SQLITE_POOL_SIZE", "20")),
        max_overflow=int(os.getenv("SQLITE_MAX_OVERFLOW", "40")),
    )
else:
    if "sslmode=require" in DATABASE_URL:
        _connect_args["sslmode"] = "require"
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=280,
        pool_size=5,
        max_overflow=2,
        connect_args=_connect_args,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    from backend.models import (
        user, face_encoding, evidence, audit_log, known_person, person_image,
        camera, alert, vehicle, config_entry, incident, custody, recording, calibration, event, camera_officer, capture, shift, push_subscription, floor_plan, jurisdiction, watchlist, detection, bolo, tracking, case_evidence, ml, dispatch,
    )
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _migrate_data()
    _adopt_legacy_watchlist()


def _adopt_legacy_watchlist():
    from backend.services.watchlist_gov import adopt_legacy
    from backend.services.vehicle_catalog import seed_defaults
    db = SessionLocal()
    try:
        if adopt_legacy(db) + seed_defaults(db):
            db.commit()
    finally:
        db.close()


def _migrate_data():
    """Idempotent data fixes for databases built by create_all (Alembic does the same in 0014)."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE incidents SET status = 'new' WHERE status = 'open'"))
        conn.execute(text("UPDATE incidents SET status = 'in_progress' WHERE status = 'investigating'"))


# (table, column, DDL type) — additive changes until Alembic baselines exist.
_ADDITIVE_COLUMNS = [
    ("alerts", "review_status", "VARCHAR(12) NOT NULL DEFAULT 'pending'"),
    ("alerts", "reviewed_by", "INTEGER"),
    ("alerts", "reviewed_at", "TIMESTAMP"),
    ("alerts", "review_note", "TEXT"),
    ("cameras", "geometry", "TEXT"),
    ("cameras", "geometry_updated_at", "TIMESTAMP"),
    ("face_encodings", "image_id", "INTEGER"),
    ("users", "phone", "VARCHAR(30)"),
    ("users", "scope_jurisdiction_id", "INTEGER REFERENCES jurisdictions(id) ON DELETE SET NULL"),
    ("users", "failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "locked_until", "TIMESTAMP"),
    ("alerts", "escalated_at", "TIMESTAMP"),
    ("cameras", "heading", "FLOAT"),
    ("cameras", "fov", "FLOAT"),
    ("cameras", "range_m", "FLOAT"),
    ("alert_captures", "encrypted", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("person_images", "encrypted", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("users", "totp_secret", "VARCHAR(255)"),
    ("users", "totp_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("users", "totp_last_step", "INTEGER"),
    ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
    ("incidents", "source", "VARCHAR(20) NOT NULL DEFAULT 'alert'"),
    ("incidents", "jurisdiction_id", "INTEGER"),
    ("incidents", "watchlist_person_id", "INTEGER"),
    ("incidents", "watchlist_vehicle_id", "INTEGER"),
    ("incidents", "cross_track_id", "INTEGER"),
    ("incident_events", "actor_id", "INTEGER"),
    ("incident_events", "camera_id", "VARCHAR(50)"),
    ("incident_events", "payload", "TEXT"),
    ("cameras", "jurisdiction_id", "INTEGER"),
    ("audit_logs", "prev_hash", "VARCHAR(64)"),
    ("audit_logs", "record_hash", "VARCHAR(64)"),
    ("cameras", "protocol", "VARCHAR(12) NOT NULL DEFAULT 'rtsp'"),
    ("cameras", "vendor", "VARCHAR(30)"),
    ("cameras", "credentials", "BLOB"),
    ("cameras", "credentials_encrypted", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("cameras", "address", "VARCHAR(200)"),
    ("cameras", "road_name", "VARCHAR(120)"),
    ("cameras", "capabilities", "TEXT"),
    ("cameras", "ir_mode", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("cameras", "status", "VARCHAR(10) NOT NULL DEFAULT 'unknown'"),
    ("cameras", "last_heartbeat", "TIMESTAMP"),
    ("cameras", "sample_fps", "FLOAT"),
    ("cameras", "priority", "INTEGER NOT NULL DEFAULT 0"),
    ("cameras", "ingest_token_hash", "VARCHAR(64)"),
    ("known_persons", "aliases", "TEXT"),
    ("known_persons", "case_no", "VARCHAR(60)"),
    ("known_persons", "offence", "VARCHAR(120)"),
    ("known_persons", "risk_level", "VARCHAR(10)"),
    ("known_persons", "issuing_authority", "VARCHAR(120)"),
    ("known_persons", "legal_basis", "TEXT"),
    ("known_persons", "wl_status", "VARCHAR(12)"),
    ("known_persons", "requested_by", "INTEGER"),
    ("known_persons", "requested_at", "TIMESTAMP"),
    ("known_persons", "approved_by", "INTEGER"),
    ("known_persons", "approved_at", "TIMESTAMP"),
    ("known_persons", "starts_at", "TIMESTAMP"),
    ("known_persons", "expires_at", "TIMESTAMP"),
    ("known_persons", "decision_note", "TEXT"),
    ("known_persons", "needs_review", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _ensure_columns():
    from sqlalchemy import inspect
    insp = inspect(engine)
    for table, col, ddl in _ADDITIVE_COLUMNS:
        if table not in insp.get_table_names():
            continue
        if col in {c["name"] for c in insp.get_columns(table)}:
            continue
        if engine.dialect.name == "postgresql":
            ddl = ddl.replace("BLOB", "BYTEA")
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        logger.info("Added column %s.%s", table, col)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
