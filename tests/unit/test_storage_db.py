import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from all3_radar.storage.db import connect


def test_connect_uses_local_sqlite_when_turso_env_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    db_path = tmp_path / "local.db"
    connection = connect(db_path)
    try:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    assert db_path.exists()
    with sqlite3.connect(db_path) as raw_connection:
        assert raw_connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sample'").fetchone()


def test_connect_uses_remote_libsql_when_turso_env_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.row_factory = None
            self.executed: list[str] = []

        def execute(self, statement: str) -> None:
            self.executed.append(statement)

    calls: list[tuple[str, str]] = []
    fake_connection = FakeConnection()

    def fake_connect(*, database: str, auth_token: str) -> FakeConnection:
        calls.append((database, auth_token))
        return fake_connection

    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "secret-token")
    monkeypatch.setitem(sys.modules, "libsql", SimpleNamespace(connect=fake_connect))

    connection = connect(tmp_path / "ignored.db")

    assert connection is fake_connection
    assert calls == [("libsql://example.turso.io", "secret-token")]
    assert fake_connection.row_factory is sqlite3.Row
    assert fake_connection.executed == ["PRAGMA foreign_keys = ON"]


def test_connect_requires_token_when_turso_url_is_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    with pytest.raises(ValueError, match="TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty"):
        connect(tmp_path / "ignored.db")
