#!/usr/bin/env python3
"""Ensure .env has real secrets and a usable DATABASE_URL before ./run.sh."""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def _gen(n: int = 48) -> str:
    return secrets.token_urlsafe(n)


def main() -> int:
    if not ENV_PATH.exists():
        if EXAMPLE.exists():
            ENV_PATH.write_text(EXAMPLE.read_text())
            print("Created .env from .env.example")
        else:
            ENV_PATH.write_text("")
            print("Created empty .env")

    text = ENV_PATH.read_text()
    changed = False

    def upsert(key: str, value: str, only_if_placeholder: bool = True) -> None:
        nonlocal text, changed
        m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
        cur = m.group(1).strip().strip('"').strip("'") if m else ""
        placeholder = (
            not cur
            or cur.startswith("CHANGE_THIS")
            or cur in {
                "change-me-in-production",
                "default-key-change-in-prod",
                "pipeline-internal-key-change-me",
            }
        )
        if m and only_if_placeholder and not placeholder:
            return
        line = f"{key}={value}"
        if m:
            text = re.sub(rf"^{re.escape(key)}=.*$", line, text, count=1, flags=re.M)
        else:
            text = text.rstrip() + f"\n{line}\n"
        changed = True
        print(f"  set {key}")

    upsert("SECRET_KEY", _gen(64))
    upsert("ENCRYPTION_KEY", _gen(32))
    upsert("ENCRYPTION_SALT", _gen(16))
    upsert("INTERNAL_API_KEY", _gen(32))
    upsert("ENVIRONMENT", "development", only_if_placeholder=False)

    # Prefer SQLite for local runs when Postgres isn't available
    db_m = re.search(r"^DATABASE_URL=(.*)$", text, re.M)
    db_url = db_m.group(1).strip().strip('"').strip("'") if db_m else ""
    use_sqlite = "USE_SQLITE=true" in text or "USE_SQLITE=1" in text

    needs_local_db = use_sqlite or (not db_url) or (
        "localhost" in db_url and "surveillance" in db_url
    ) or db_url.startswith("postgresql://surveillance:")

    if needs_local_db:
        sqlite_url = f"sqlite:///{(ROOT / 'data' / 'ai_sss.db').as_posix()}"
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        upsert("USE_SQLITE", "true", only_if_placeholder=False)
        upsert("DATABASE_URL", sqlite_url, only_if_placeholder=False)
        upsert("ALLOW_SQLITE_FALLBACK", "true", only_if_placeholder=False)
        print(f"  local DB → {sqlite_url}")

    if changed:
        ENV_PATH.write_text(text)
        print("Updated .env")
    else:
        print(".env already OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
