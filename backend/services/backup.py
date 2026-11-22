"""Backups of everything needed to rebuild the system's records.

The database holds users, cameras, alerts, incidents, the shift log, face records and evidence
and capture images, so one consistent copy of it is most of a backup; the config files are
added. Recordings are large and expire after DVR_RETENTION_HOURS anyway: included only with
BACKUP_RECORDINGS=true.

    data/backups/20261123_0300/
        aegis.db | aegis.sql.gz     SQLite online-backup copy, or pg_dump of PostgreSQL
        config/*.yaml
        recordings/...              only with BACKUP_RECORDINGS=true
        backup.json                 what is inside, sizes, SHA-256 of the database copy

The newest BACKUP_KEEP (default 7) are kept. Restore: docs/OPERATIONS.md.
"""

import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from clock import utcnow
from paths import CONFIG_DIR, DATA_DIR, RECORDINGS_DIR

logger = logging.getLogger("HumanAnalysis")
NAME = re.compile(r"^\d{8}_\d{4}$")          # only folders this module made are ever removed


def backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR") or DATA_DIR / "backups")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _database(dest: Path) -> Path:
    from backend.db.database import engine

    url = engine.url
    if url.get_backend_name() == "sqlite":
        out = dest / "aegis.db"
        src = sqlite3.connect(url.database)
        dst = sqlite3.connect(out)
        with dst:
            src.backup(dst)                 # consistent copy while the app keeps writing
        src.close()
        dst.close()
        return out
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump not found: install the PostgreSQL client to back up this database")
    out = dest / "aegis.sql.gz"
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    args = [pg_dump, "--no-owner", "-h", url.host or "localhost", "-p", str(url.port or 5432),
            "-U", url.username or "postgres", url.database]
    dump = subprocess.run(args, capture_output=True, env=env, timeout=3600)
    if dump.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {dump.stderr.decode()[:300]}")
    with gzip.open(out, "wb") as f:
        f.write(dump.stdout)
    return out


def run_backup(keep: int = None, recordings: bool = None) -> dict:
    keep = keep if keep is not None else int(os.getenv("BACKUP_KEEP", "7"))
    recordings = recordings if recordings is not None else os.getenv("BACKUP_RECORDINGS", "false").lower() == "true"
    root = backup_dir()
    dest = root / utcnow().strftime("%Y%m%d_%H%M")
    dest.mkdir(parents=True, exist_ok=True)
    db_file = _database(dest)
    shutil.copytree(CONFIG_DIR, dest / "config", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.local*"))
    if recordings and RECORDINGS_DIR.exists():
        shutil.copytree(RECORDINGS_DIR, dest / "recordings", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.web.mp4", "*.tmp.mp4"))
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    info = {"name": dest.name, "created_at": utcnow().isoformat(), "database": db_file.name,
            "database_sha256": _sha256(db_file), "recordings": recordings, "bytes": size}
    (dest / "backup.json").write_text(json.dumps(info, indent=2))

    old = sorted((p for p in root.iterdir() if p.is_dir() and NAME.match(p.name)), reverse=True)[max(keep, 1):]
    for p in old:
        shutil.rmtree(p)
    info["removed_old"] = [p.name for p in old]
    logger.info(f"Backup {dest.name}: {size / 1e6:.1f} MB ({len(old)} old removed)")
    return info


def list_backups() -> list:
    root = backup_dir()
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir(), reverse=True):
        meta = p / "backup.json"
        if p.is_dir() and NAME.match(p.name) and meta.exists():
            out.append(json.loads(meta.read_text()))
    return out
