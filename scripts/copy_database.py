#!/usr/bin/env python3
"""Copy every Aegis table from one database to another (e.g. the local SQLite file to PostgreSQL).

The target schema is created from the models and stamped at the current Alembic revision, then
rows are copied table by table in dependency order (parents before children), in batches. On
PostgreSQL the id sequences are moved past the copied ids. The source is only read.

    python scripts/copy_database.py --to postgresql://aegis:PASS@localhost:5432/aegis
    python scripts/copy_database.py --from sqlite:///data/ai_sss.db --to ... --replace
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import create_engine, func, select, text  # noqa: E402

BATCH = 500


def _models():
    from backend.db import database
    from backend.models import (  # noqa: F401  (registers every table on Base.metadata)
        user, face_encoding, evidence, audit_log, known_person, person_image, camera, alert, vehicle,
        config_entry, incident, custody, recording, calibration, event, camera_officer, capture, shift, push_subscription, floor_plan,
    )
    return database.Base.metadata


def copy_database(source_url: str, target_url: str, replace: bool = False, log=print) -> dict:
    meta = _models()
    src = create_engine(source_url)
    dst = create_engine(target_url)
    meta.create_all(dst)
    counts = {}
    with src.connect() as s, dst.begin() as d:
        existing = {t.name for t in meta.sorted_tables
                    if d.execute(select(func.count()).select_from(t)).scalar()}
        if existing and not replace:
            raise SystemExit(f"Target already has data in: {', '.join(sorted(existing))}. Use --replace to overwrite.")
        for table in reversed(meta.sorted_tables):            # children first when emptying
            d.execute(table.delete())
        src_tables = set(src.dialect.get_table_names(s))
        for table in meta.sorted_tables:                      # parents first when filling
            if table.name not in src_tables:
                continue
            cols = [c.name for c in table.columns if c.name in {x["name"] for x in src.dialect.get_columns(s, table.name)}]
            rows = s.execute(select(*[table.c[c] for c in cols])).mappings()
            n = 0
            while True:
                batch = rows.fetchmany(BATCH)
                if not batch:
                    break
                d.execute(table.insert(), [dict(r) for r in batch])
                n += len(batch)
            counts[table.name] = n
            log(f"  {table.name}: {n}")
        if dst.dialect.name == "postgresql":                  # next id after the copied ones
            for table in meta.sorted_tables:
                if "id" in table.c and table.c.id.autoincrement:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                                   f"COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"))
    _stamp(target_url)
    return counts


def _stamp(url: str) -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    os.environ["DATABASE_URL"] = url
    command.stamp(cfg, "head")


if __name__ == "__main__":
    from backend.db.database import DEFAULT_SQLITE
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="source", default=DEFAULT_SQLITE, help="source database URL (default: the local SQLite file)")
    p.add_argument("--to", dest="target", required=True, help="target database URL")
    p.add_argument("--replace", action="store_true", help="empty the target's tables first")
    a = p.parse_args()
    print(f"Copying {a.source} -> {a.target.split('@')[-1]}")
    done = copy_database(a.source, a.target, a.replace)
    print(f"Done: {sum(done.values())} rows in {len(done)} tables. Now set DATABASE_URL in .env and USE_SQLITE=false.")
