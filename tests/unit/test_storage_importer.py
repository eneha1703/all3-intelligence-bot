from __future__ import annotations

import sqlite3
from pathlib import Path

from all3_radar.storage.importer import import_sqlite_database


def _insert_sample_rows(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            INSERT INTO sources (
              id, name, kind, layer, is_direct_source, is_wrapper, enabled,
              base_url, config_json, created_at
            ) VALUES (
              'source-1', 'Source One', 'rss', 'core', 1, 0, 1,
              'https://example.com', '{}', '2026-05-17T00:00:00Z'
            );

            INSERT INTO pipeline_runs (
              id, pipeline, started_at, finished_at, status, config_snapshot_json, summary_json
            ) VALUES (
              'run-1', 'radar', '2026-05-17T00:00:00Z', '2026-05-17T00:01:00Z',
              'completed', '{}', '{}'
            );

            INSERT INTO raw_items (
              id, run_id, source_id, external_id, url, title, snippet, author,
              published_ts, collected_ts, raw_payload_json, fetch_status
            ) VALUES (
              'raw-1', 'run-1', 'source-1', 'ext-1', 'https://example.com/story',
              'Story title', 'Snippet', 'Author', '2026-05-17T00:00:00Z',
              '2026-05-17T00:00:05Z', '{}', 'ok'
            );

            INSERT INTO normalized_items (
              id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview,
              published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json
            ) VALUES (
              'norm-1', 'raw-1', 'source-1', 'https://example.com/story', 'example.com',
              'Story title', NULL, 'Preview', '2026-05-17T00:00:00Z', '2026-05-17T00:00:05Z',
              'en', 'core', 0, 10, '{}'
            );

            INSERT INTO canonical_events (
              id, representative_item_id, event_key, cluster_title,
              first_published_ts, last_published_ts, created_at, updated_at
            ) VALUES (
              'event-1', 'norm-1', 'event-key-1', 'Cluster title',
              '2026-05-17T00:00:00Z', '2026-05-17T00:00:00Z',
              '2026-05-17T00:00:10Z', '2026-05-17T00:00:10Z'
            );

            INSERT INTO event_members (
              canonical_event_id, normalized_item_id, is_representative
            ) VALUES (
              'event-1', 'norm-1', 1
            );

            INSERT INTO radar_decisions (
              normalized_item_id, canonical_event_id, freshness_status, relevance_status,
              send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at
            ) VALUES (
              'norm-1', 'event-1', 'fresh', 'keep', 'sent', NULL, 77,
              '{}', 'Summary', 0, '2026-05-17T00:00:20Z'
            );
            """
        )
        connection.commit()


def _initialize_schema(database_path: Path, schema_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        connection.commit()


def test_import_sqlite_database_copies_rows(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"

    _initialize_schema(source_path, schema_path)
    _insert_sample_rows(source_path)

    imported_counts = import_sqlite_database(
        source_database_path=source_path,
        target_database_path=target_path,
        schema_path=schema_path,
        batch_size=2,
    )

    assert imported_counts["sources"] == 1
    assert imported_counts["pipeline_runs"] == 1
    assert imported_counts["raw_items"] == 1
    assert imported_counts["normalized_items"] == 1
    assert imported_counts["canonical_events"] == 1
    assert imported_counts["event_members"] == 1
    assert imported_counts["radar_decisions"] == 1

    with sqlite3.connect(target_path) as connection:
        row = connection.execute(
            "SELECT canonical_event_id, send_status, score FROM radar_decisions WHERE normalized_item_id = 'norm-1'"
        ).fetchone()
    assert row == ("event-1", "sent", 77)


def test_import_sqlite_database_overwrites_existing_target_rows(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"

    _initialize_schema(source_path, schema_path)
    _initialize_schema(target_path, schema_path)
    _insert_sample_rows(source_path)

    with sqlite3.connect(target_path) as connection:
        connection.execute(
            """
            INSERT INTO integration_cursors (consumer_key, cursor_value, updated_at)
            VALUES ('cursor-1', 'old', '2026-05-16T00:00:00Z')
            """
        )
        connection.commit()

    imported_counts = import_sqlite_database(
        source_database_path=source_path,
        target_database_path=target_path,
        schema_path=schema_path,
    )

    assert imported_counts["integration_cursors"] == 0
    with sqlite3.connect(target_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM integration_cursors").fetchone()[0]
    assert count == 0
