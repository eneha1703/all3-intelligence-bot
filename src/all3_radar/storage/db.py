"""SQLite initialization helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path, schema_path: Path) -> None:
    schema = schema_path.read_text(encoding="utf-8")
    with connect(database_path) as connection:
        connection.executescript(schema)
        connection.commit()
