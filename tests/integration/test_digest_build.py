import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.digest.claude_client import ClaudeDigestUnavailableError
from all3_radar.digest.digest_service import DigestService
from all3_radar.storage.db import initialize_database


def _seed_digest_db(db_path: Path, schema_path: Path) -> None:
    initialize_database(db_path, schema_path)
    now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).isoformat()
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
            INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, base_url, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("destatis_press", "Destatis", "listing", "direct", 1, 0, 1, "https://example.com/destatis", "{}", now),
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (id, pipeline, started_at, finished_at, status, config_snapshot_json, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("radar-run-1", "radar", now, now, "completed", "{}", "{}"),
        )

        raw_rows = [
            (
                "raw-1",
                "item-1",
                "event-1",
                "German construction orders recover before capacity does",
                "https://example.com/destatis-orders",
                "destatis_press",
                95,
                "Destatis data showed orders recovering before labor and site capacity normalized.",
                '{"event_flags":{"construction_statistics_signal":true,"construction_innovation_signal":true}}',
            ),
            (
                "raw-2",
                "item-2",
                "event-2",
                "Sereact scales physical AI reliability after fresh funding",
                "https://example.com/sereact",
                "robot_report_rss",
                92,
                "Sereact framed the round around deployment reliability and warehouse production metrics.",
                '{"event_flags":{"funding_event":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-3",
                "item-3",
                "event-3",
                "SoftBank and Roze turn AI infrastructure into a robotics delivery problem",
                "https://example.com/softbank-roze",
                "robot_report_rss",
                89,
                "The story tied data-center construction and physical infrastructure delivery to automation constraints.",
                '{"event_flags":{"funding_event":true,"construction_innovation_signal":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-4",
                "item-4",
                "event-4",
                "Mass timber school pipeline points to repeatable civic deployment",
                "https://example.com/mass-timber",
                "robot_report_rss",
                86,
                "The project mix showed repeatable timber deployment patterns rather than a one-off design feature.",
                '{"event_flags":{"timber_strategic_signal":true}}',
            ),
            (
                "raw-5",
                "item-5",
                "event-5",
                "Flex and Teradyne expand partnership to scale physical AI",
                "https://example.com/flex",
                "robot_report_rss",
                84,
                "Flex and Teradyne expanded manufacturing execution partnerships around physical AI deployment.",
                '{"event_flags":{"partnership_event":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-6",
                "item-6",
                "event-6",
                "Taco Bell adds AI menu personalization",
                "https://example.com/tacobell",
                "robot_report_rss",
                70,
                "The update focused on consumer menu recommendations rather than operational automation.",
                '{"event_flags":{"partnership_event":true}}',
            ),
        ]
        for raw_id, item_id, event_id, title, url, source_id, score, summary_text, signals_json in raw_rows:
            connection.execute(
                """
                INSERT INTO raw_items (id, run_id, source_id, external_id, url, title, snippet, author, published_ts, collected_ts, raw_payload_json, fetch_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (raw_id, "radar-run-1", source_id, None, url, title, None, None, now, now, "{}", "collected"),
            )
            connection.execute(
                """
                INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    raw_id,
                    source_id,
                    url,
                    "example.com",
                    title,
                    None,
                    f"Preview for {title}",
                    now,
                    now,
                    "de" if source_id == "destatis_press" else "en",
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
                    "sent" if item_id in {"item-1", "item-2"} else "stored_only",
                    None,
                    score,
                    signals_json,
                    summary_text,
                    0,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, item_id, event_id, title, now, now, now, now),
            )
            connection.execute(
                """
                INSERT INTO event_members (canonical_event_id, normalized_item_id, is_representative)
                VALUES (?, ?, ?)
                """,
                (event_id, item_id, 1),
            )
        connection.commit()


class _FakeClaudeClient:
    is_available = True

    def __init__(self) -> None:
        self.selection_prompts: list[str] = []
        self.writer_prompts: list[str] = []

    def select_top_story_ids(self, prompt: str, *, allowed_ids: set[str], exact_count: int = 5) -> list[str]:
        self.selection_prompts.append(prompt)
        assert exact_count == 5
        selected_ids = ["event-1", "event-2", "event-3", "event-4", "event-5"]
        assert len(selected_ids) == len(set(selected_ids))
        assert set(selected_ids).issubset(allowed_ids)
        return selected_ids

    def generate_telegram_digest(self, prompt: str, *, expected_title: str) -> str:
        self.writer_prompts.append(prompt)
        assert "German construction orders recover before capacity does" in prompt
        assert "Taco Bell adds AI menu personalization" not in prompt
        return "\n\n".join(
            [
                expected_title,
                '1. <b>German construction orders recover before capacity does</b>\n'
                'Destatis suggests that order intake is recovering ahead of labor and site capacity, which matters because upstream demand is returning before the industry can fully execute. <a href="https://example.com/destatis-orders">Link</a>',
                '2. <b>Sereact turns funding into a reliability test for warehouse physical AI</b>\n'
                'The funding matters less as capital than as a signal that customers now expect measurable production reliability from warehouse robotics platforms. <a href="https://example.com/sereact">Link</a>',
                '3. <b>SoftBank and Roze show AI infrastructure becoming a physical automation problem</b>\n'
                'The strategic signal is that data-center growth now depends on construction and delivery automation, not just compute budgets. <a href="https://example.com/softbank-roze">Link</a>',
                '4. <b>Mass timber moves from showcase projects toward repeatable civic deployment</b>\n'
                'The typology mix suggests timber adoption is broadening into replicable public-sector delivery rather than isolated demonstration work. <a href="https://example.com/mass-timber">Link</a>',
                '5. <b>Flex and Teradyne deepen the manufacturing stack around physical AI</b>\n'
                'This partnership matters because it connects physical AI deployment to production execution capacity inside existing industrial networks. <a href="https://example.com/flex">Link</a>',
            ]
        )


class _FailingClaudeClient:
    is_available = True

    def select_top_story_ids(self, prompt: str, *, allowed_ids: set[str], exact_count: int = 5) -> list[str]:
        raise ClaudeDigestUnavailableError("timeout")

    def generate_telegram_digest(self, prompt: str, *, expected_title: str) -> str:
        raise ClaudeDigestUnavailableError("timeout")


def test_digest_build_generates_telegram_ready_artifact_with_claude(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "weekly_digest_2026-W18.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "true")

    fake_client = _FakeClaudeClient()
    service = DigestService(repo_root=repo_root, claude_client=fake_client)
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 6
    assert result.claude_used is True
    assert result.fallback_reason is None

    digest_text = output_path.read_text(encoding="utf-8")
    assert digest_text.startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert '<a href="https://example.com/destatis-orders">Link</a>' in digest_text
    assert "https://example.com/destatis-orders" not in digest_text.replace(
        '<a href="https://example.com/destatis-orders">Link</a>', ""
    )
    assert "Taco Bell adds AI menu personalization" not in digest_text
    assert "Destatis suggests that order intake is recovering" in digest_text

    report_path = tmp_path / "weekly_digest_2026-W18.report.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "## Top Stories" in report_text
    assert "German construction orders recover before capacity does" in report_text

    assert len(fake_client.selection_prompts) == 1
    assert len(fake_client.writer_prompts) == 1


def test_digest_build_falls_back_to_deterministic_artifact_without_claude(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "weekly_digest_2026-W18.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "true")

    service = DigestService(repo_root=repo_root, claude_client=_FailingClaudeClient())
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 6
    assert result.claude_used is False
    assert result.fallback_reason == "timeout"
    digest_text = output_path.read_text(encoding="utf-8")
    assert digest_text.startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert '<a href="https://example.com/destatis-orders">Link</a>' in digest_text
    assert "Taco Bell adds AI menu personalization" not in digest_text

    with sqlite3.connect(db_path) as connection:
        digest_row = connection.execute(
            "SELECT status, final_digest_markdown FROM weekly_digest_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        candidate_count = connection.execute("SELECT COUNT(*) FROM weekly_digest_candidates").fetchone()[0]

    assert digest_row[0] == "completed"
    assert digest_row[1].startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert candidate_count == 6
