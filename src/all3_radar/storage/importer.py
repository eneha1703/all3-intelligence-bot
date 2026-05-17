"""Import local SQLite state into another SQLite/libSQL database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from .db import connect, initialize_database

TABLE_IMPORT_ORDER = [
    "sources",
    "pipeline_runs",
    "integration_cursors",
    "raw_items",
    "normalized_items",
    "canonical_events",
    "competitor_matches",
    "event_members",
    "radar_decisions",
    "telegram_deliveries",
    "telegram_group_messages",
    "telegram_group_message_links",
    "telegram_reaction_picks",
    "editorial_signals",
    "weekly_digest_runs",
    "weekly_digest_candidates",
]

RETRYABLE_STREAM_ERROR_SNIPPETS = (
    "stream not found",
    "stream error",
)


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


def _ordered_table_names(table_names: list[str]) -> list[str]:
    table_name_set = set(table_names)
    ordered = [table_name for table_name in TABLE_IMPORT_ORDER if table_name in table_name_set]
    ordered_set = set(ordered)
    remaining = sorted(table_name for table_name in table_names if table_name not in ordered_set)
    return ordered + remaining


def _table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return [str(row[1]) for row in rows]


def _delete_target_rows(connection: Any, table_names: list[str]) -> None:
    for table_name in table_names:
        connection.execute(f"DELETE FROM {_quote_identifier(table_name)}")


def _is_retryable_stream_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(snippet in message for snippet in RETRYABLE_STREAM_ERROR_SNIPPETS)


def _write_batch(
    *,
    target_database_path: Path,
    insert_sql: str,
    batch: list[tuple[Any, ...]],
    table_name: str,
    progress_callback: Callable[[str], None] | None = None,
    max_retries: int = 3,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with connect(target_database_path) as target_connection:
                target_connection.executemany(insert_sql, batch)
                target_connection.commit()
            return
        except Exception as exc:  # pragma: no cover - exercised via remote runtime
            last_exc = exc
            if not _is_retryable_stream_error(exc) or attempt >= max_retries:
                raise
            if progress_callback is not None:
                progress_callback(
                    f"   retrying {table_name} batch after transient Turso stream error "
                    f"(attempt {attempt}/{max_retries})..."
                )
    if last_exc is not None:
        raise last_exc


def _copy_table(
    source_connection: sqlite3.Connection,
    target_database_path: Path,
    table_name: str,
    *,
    batch_size: int = 500,
    progress_callback: Callable[[str], None] | None = None,
) -> int:
    column_names = _table_columns(source_connection, table_name)
    quoted_columns = ", ".join(_quote_identifier(name) for name in column_names)
    placeholders = ", ".join("?" for _ in column_names)
    select_sql = f"SELECT {quoted_columns} FROM {_quote_identifier(table_name)}"
    insert_sql = (
        f"INSERT OR REPLACE INTO {_quote_identifier(table_name)} ({quoted_columns}) "
        f"VALUES ({placeholders})"
    )

    copied_rows = 0
    batch: list[tuple[Any, ...]] = []
    cursor = source_connection.execute(select_sql)
    for row in cursor:
        batch.append(tuple(row[column_name] for column_name in column_names))
        if len(batch) >= batch_size:
            _write_batch(
                target_database_path=target_database_path,
                insert_sql=insert_sql,
                batch=batch,
                table_name=table_name,
                progress_callback=progress_callback,
            )
            copied_rows += len(batch)
            if progress_callback is not None:
                progress_callback(
                    f"   imported {copied_rows} rows into {table_name}..."
                )
            batch.clear()
    if batch:
        _write_batch(
            target_database_path=target_database_path,
            insert_sql=insert_sql,
            batch=batch,
            table_name=table_name,
            progress_callback=progress_callback,
        )
        copied_rows += len(batch)
        if progress_callback is not None:
            progress_callback(f"   imported {copied_rows} rows into {table_name}...")
    return copied_rows


def import_sqlite_database(
    *,
    source_database_path: Path,
    target_database_path: Path,
    schema_path: Path,
    batch_size: int = 500,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, int]:
    if not source_database_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_database_path}")

    with sqlite3.connect(source_database_path) as source_connection:
        source_connection.row_factory = sqlite3.Row
        table_names = _ordered_table_names(_list_user_tables(source_connection))
        if progress_callback is not None:
            progress_callback(
                f"Opened source database {source_database_path} with {len(table_names)} tables."
            )

        initialize_database(target_database_path, schema_path)
        if progress_callback is not None:
            progress_callback("Initialized target schema.")
        with connect(target_database_path) as target_connection:
            if progress_callback is not None:
                progress_callback("Connected to target database. Clearing existing rows...")
            _delete_target_rows(target_connection, list(reversed(table_names)))
            target_connection.commit()
            imported_counts: dict[str, int] = {}
            total_tables = len(table_names)
            for table_index, table_name in enumerate(table_names, start=1):
                if progress_callback is not None:
                    progress_callback(f"[{table_index}/{total_tables}] Importing {table_name}...")
                imported_counts[table_name] = _copy_table(
                    source_connection,
                    target_database_path,
                    table_name,
                    batch_size=batch_size,
                    progress_callback=progress_callback,
                )
                if progress_callback is not None:
                    progress_callback(
                        f"[{table_index}/{total_tables}] Finished {table_name}: {imported_counts[table_name]} rows."
                    )
            if progress_callback is not None:
                progress_callback("Import committed successfully.")
            return imported_counts
