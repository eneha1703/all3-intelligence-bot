"""SQLite initialization helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def initialize_database(database_path: Path, schema_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    schema = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema)
        connection.commit()
