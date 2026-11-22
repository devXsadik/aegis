"""copy_database: every table, rows and relations intact, refuses to overwrite by accident."""

import sqlite3

import pytest

from scripts.copy_database import copy_database


def test_copies_the_real_database_and_guards_the_target(tmp_path):
    import shutil
    from backend.db.database import DEFAULT_SQLITE, init_db
    init_db()
    src_file = tmp_path / "src.db"
    shutil.copy(DEFAULT_SQLITE.replace("sqlite:///", ""), src_file)    # a copy: the source is only read anyway
    src, dst = f"sqlite:///{src_file}", f"sqlite:///{tmp_path / 'dst.db'}"
    counts = copy_database(src, dst, log=lambda *_: None)

    a, b = sqlite3.connect(src_file), sqlite3.connect(tmp_path / "dst.db")
    for table, n in counts.items():
        assert b.execute(f"select count(*) from {table}").fetchone()[0] == n
        assert a.execute(f"select count(*) from {table}").fetchone()[0] == n
    assert b.execute("select version_num from alembic_version").fetchone()[0]       # stamped at head
    with pytest.raises(SystemExit, match="already has data"):
        copy_database(src, dst, log=lambda *_: None)
    if any(counts.values()):
        assert copy_database(src, dst, replace=True, log=lambda *_: None) == counts
