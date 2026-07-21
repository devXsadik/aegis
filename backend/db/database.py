import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()


def _normalize_database_url(url: str) -> str:
    """Render and other cloud Postgres providers require SSL."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

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


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", "postgresql://surveillance:surveillance@localhost:5432/surveillance_db")
)

_connect_args = {}
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
        camera, alert, vehicle, config_entry, incident, custody, recording, calibration,
    )
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

