"""SQLite and libSQL initialization helpers."""

from __future__ import annotations

import importlib
import os
import sqlite3
from pathlib import Path
from typing import Any


def _remote_database_env() -> tuple[str | None, str | None]:
    database_url = (os.environ.get("TURSO_DATABASE_URL") or "").strip() or None
    auth_token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip() or None
    return database_url, auth_token


def _configure_connection(connection: Any) -> None:
    try:
        connection.row_factory = sqlite3.Row
    except Exception:
        pass
    connection.execute("PRAGMA foreign_keys = ON")


def connect(database_path: Path) -> Any:
    database_url, auth_token = _remote_database_env()
    if database_url:
        if not auth_token:
            raise ValueError("TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty.")
        try:
            libsql = importlib.import_module("libsql")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Remote database mode requires the 'libsql' package. Install project dependencies with libsql support."
            ) from exc
        connection = libsql.connect(database=database_url, auth_token=auth_token)
        _configure_connection(connection)
        return connection

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    _configure_connection(connection)
    return connection


def initialize_database(database_path: Path, schema_path: Path) -> None:
    schema = schema_path.read_text(encoding="utf-8")
    with connect(database_path) as connection:
        connection.executescript(schema)
        connection.commit()
