"""Import local SQLite state into another SQLite/libSQL database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .db import connect, initialize_database


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _list_user_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return [str(row[1]) for row in rows]


def _delete_target_rows(connection: Any, table_names: list[str]) -> None:
    for table_name in table_names:
        connection.execute(f"DELETE FROM {_quote_identifier(table_name)}")


def _copy_table(
    source_connection: sqlite3.Connection,
    target_connection: Any,
    table_name: str,
    *,
    batch_size: int = 500,
) -> int:
    column_names = _table_columns(source_connection, table_name)
    quoted_columns = ", ".join(_quote_identifier(name) for name in column_names)
    placeholders = ", ".join("?" for _ in column_names)
    select_sql = f"SELECT {quoted_columns} FROM {_quote_identifier(table_name)}"
    insert_sql = (
        f"INSERT INTO {_quote_identifier(table_name)} ({quoted_columns}) "
        f"VALUES ({placeholders})"
    )

    copied_rows = 0
    batch: list[tuple[Any, ...]] = []
    cursor = source_connection.execute(select_sql)
    for row in cursor:
        batch.append(tuple(row[column_name] for column_name in column_names))
        if len(batch) >= batch_size:
            target_connection.executemany(insert_sql, batch)
            copied_rows += len(batch)
            batch.clear()
    if batch:
        target_connection.executemany(insert_sql, batch)
        copied_rows += len(batch)
    return copied_rows


def import_sqlite_database(
    *,
    source_database_path: Path,
    target_database_path: Path,
    schema_path: Path,
    batch_size: int = 500,
) -> dict[str, int]:
    if not source_database_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_database_path}")

    with sqlite3.connect(source_database_path) as source_connection:
        source_connection.row_factory = sqlite3.Row
        table_names = _list_user_tables(source_connection)

        initialize_database(target_database_path, schema_path)
        with connect(target_database_path) as target_connection:
            target_connection.execute("PRAGMA foreign_keys = OFF")
            _delete_target_rows(target_connection, table_names)
            imported_counts: dict[str, int] = {}
            for table_name in table_names:
                imported_counts[table_name] = _copy_table(
                    source_connection,
                    target_connection,
                    table_name,
                    batch_size=batch_size,
                )
            target_connection.execute("PRAGMA foreign_keys = ON")
            target_connection.commit()
            return imported_counts
