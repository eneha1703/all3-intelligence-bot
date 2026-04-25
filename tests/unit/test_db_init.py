import sqlite3
from pathlib import Path

from all3_radar.storage.db import initialize_database


def test_initialize_database_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    schema_path = Path(__file__).resolve().parents[2] / "src" / "all3_radar" / "storage" / "schema.sql"

    initialize_database(db_path, schema_path)

    with sqlite3.connect(db_path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "sources" in names
    assert "weekly_digest_runs" in names
