import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.digest.claude_client import ClaudeDigestUnavailableError
from all3_radar.digest.digest_service import DigestService
from all3_radar.storage.db import initialize_database


def _seed_digest_db(db_path: Path, schema_path: Path) -> None:
    initialize_database(db_path, schema_path)
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, base_url, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("robot_report_rss", "Robot Report", "rss", "direct", 1, 0, 1, "https://example.com/feed", "{}", now),
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (id, pipeline, started_at, finished_at, status, config_snapshot_json, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("radar-run-1", "radar", now, now, "completed", "{}", "{}"),
        )

        raw_rows = [
            ("raw-1", "item-1", "event-1", "All3 raises $25M in seed funding", "https://example.com/all3-1", 91),
            ("raw-2", "item-2", "event-1", "Construction startup All3 lands $25M round", "https://example.com/all3-2", 72),
            ("raw-3", "item-3", "event-2", "Flex and Teradyne expand partnership to scale physical AI", "https://example.com/flex", 84),
        ]
        for raw_id, item_id, event_id, title, url, score in raw_rows:
            connection.execute(
                """
                INSERT INTO raw_items (id, run_id, source_id, external_id, url, title, snippet, author, published_ts, collected_ts, raw_payload_json, fetch_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (raw_id, "radar-run-1", "robot_report_rss", None, url, title, None, None, now, now, "{}", "collected"),
            )
            connection.execute(
                """
                INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    raw_id,
                    "robot_report_rss",
                    url,
                    "example.com",
                    title,
                    None,
                    f"Preview for {title}",
                    now,
                    now,
                    "en",
                    "direct",
                    0,
                    100,
                    "{}",
                ),
            )
            connection.execute(
                """
                INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    event_id,
                    "fresh",
                    "keep",
                    "sent" if item_id == "item-1" else "stored_only",
                    None,
                    score,
                    '{"event_flags":{"funding_event":true,"industrial_robotics_signal":true}}'
                    if event_id == "event-1"
                    else '{"event_flags":{"partnership_event":true,"industrial_robotics_signal":true}}',
                    f"Stored summary for {title}",
                    0,
                    now,
                ),
            )

        connection.execute(
            """
            INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("event-1", "item-1", "all3-funding", "All3 raises $25M in seed funding", now, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("event-2", "item-3", "flex-teradyne-partnership", "Flex and Teradyne expand partnership to scale physical AI", now, now, now, now),
        )
        connection.executemany(
            """
            INSERT INTO event_members (canonical_event_id, normalized_item_id, is_representative)
            VALUES (?, ?, ?)
            """,
            [
                ("event-1", "item-1", 1),
                ("event-1", "item-2", 0),
                ("event-2", "item-3", 1),
            ],
        )
        connection.commit()


class _FailingClaudeClient:
    is_available = True

    def generate_digest_section(self, prompt: str) -> str:
        raise ClaudeDigestUnavailableError("timeout")


def test_digest_build_writes_markdown_and_falls_back_without_claude(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "digest.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "true")

    service = DigestService(
        repo_root=repo_root,
        claude_client=_FailingClaudeClient(),
    )
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 2
    assert result.claude_used is False
    assert result.fallback_reason == "timeout"
    markdown = output_path.read_text(encoding="utf-8")
    assert "All3 raises $25M in seed funding" in markdown
    assert "Construction startup All3 lands $25M round" not in markdown
    assert "## Claude Synthesis" not in markdown
    assert "## Top Stories" in markdown

    with sqlite3.connect(db_path) as connection:
        digest_row = connection.execute(
            "SELECT status, final_digest_markdown FROM weekly_digest_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        candidate_count = connection.execute("SELECT COUNT(*) FROM weekly_digest_candidates").fetchone()[0]

    assert digest_row[0] == "completed"
    assert "All3 raises $25M in seed funding" in digest_row[1]
    assert candidate_count == 2
