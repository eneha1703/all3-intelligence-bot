from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from all3_radar.domain.models import ClaudeFinalCardResult


def _load_preview_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "claude_final_card_preview.py"
    spec = importlib.util.spec_from_file_location("claude_final_card_preview", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


preview = _load_preview_module()


class _FakeClaudeClient:
    def __init__(self, result_by_title: dict[str, ClaudeFinalCardResult] | None = None, errors: dict[str, Exception] | None = None) -> None:
        self.result_by_title = result_by_title or {}
        self.errors = errors or {}
        self.calls: list[str] = []

    def generate_final_card(self, **kwargs):
        title = kwargs["title"]
        self.calls.append(title)
        if title in self.errors:
            raise self.errors[title]
        return self.result_by_title[title]


class _FakeSender:
    def __init__(self, configured: bool = True) -> None:
        self._configured = configured
        self.sent_cards = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    def send_card(self, card):
        self.sent_cards.append(card)
        return []


def _create_artifact_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "artifact.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE raw_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            external_id TEXT,
            url TEXT NOT NULL,
            title TEXT,
            snippet TEXT,
            author TEXT,
            published_ts TEXT,
            collected_ts TEXT NOT NULL,
            raw_payload_json TEXT NOT NULL,
            fetch_status TEXT NOT NULL
        );
        CREATE TABLE normalized_items (
            id TEXT PRIMARY KEY,
            raw_item_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            domain TEXT NOT NULL,
            title TEXT NOT NULL,
            dek TEXT,
            text_preview TEXT,
            published_ts TEXT,
            collected_ts TEXT NOT NULL,
            language TEXT,
            layer TEXT NOT NULL,
            is_wrapper INTEGER NOT NULL,
            directness_rank INTEGER NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE radar_decisions (
            normalized_item_id TEXT PRIMARY KEY,
            canonical_event_id TEXT,
            freshness_status TEXT NOT NULL,
            relevance_status TEXT NOT NULL,
            send_status TEXT NOT NULL,
            skip_reason TEXT,
            score INTEGER NOT NULL,
            signals_json TEXT NOT NULL,
            summary_text TEXT,
            used_gemini INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            layer TEXT NOT NULL,
            is_direct_source INTEGER NOT NULL,
            is_wrapper INTEGER NOT NULL,
            enabled INTEGER NOT NULL,
            parser TEXT NOT NULL,
            url TEXT NOT NULL,
            priority INTEGER NOT NULL,
            tags_json TEXT NOT NULL,
            extra_config_json TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, parser, url, priority, tags_json, extra_config_json)
        VALUES ('robot_report_rss', 'The Robot Report', 'rss', 'direct', 1, 0, 1, 'rss', 'https://example.com', 1, '[]', '{}')
        """
    )
    stories = [
        (
            "raw-1",
            "norm-1",
            "run-123",
            "Teradyne Robotics revenue rises at the start of 2026",
            "https://www.therobotreport.com/teradyne-robotics-revenue-rises-start-2026/",
            "Teradyne Robotics brought in $91 million in Q1 2026, up from $69 million a year earlier.",
            "Teradyne Robotics brought in $91 million in Q1 2026, up from $69 million a year earlier.",
            40,
        ),
        (
            "raw-2",
            "norm-2",
            "run-123",
            "Launchpad Build AI offers MLM to speed industrial automation design",
            "https://www.therobotreport.com/launchpad-build-ai-offers-manufacturing-language-model-industrial-automation/",
            "Launchpad Build AI says its Manufacturing Language Model can design automation workflows from photos, videos, or CAD.",
            "Launchpad Build AI says its Manufacturing Language Model can design automation workflows from photos, videos, or CAD.",
            33,
        ),
    ]
    for raw_id, norm_id, run_id, title, url, preview_text, summary_text, score in stories:
        connection.execute(
            """
            INSERT INTO raw_items (id, run_id, source_id, external_id, url, title, snippet, author, published_ts, collected_ts, raw_payload_json, fetch_status)
            VALUES (?, ?, 'robot_report_rss', NULL, ?, ?, NULL, NULL, NULL, '2026-05-01T00:00:00+00:00', '{}', 'fetched')
            """,
            (raw_id, run_id, url, title),
        )
        connection.execute(
            """
            INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
            VALUES (?, ?, 'robot_report_rss', ?, 'therobotreport.com', ?, NULL, ?, NULL, '2026-05-01T00:00:00+00:00', 'en', 'direct', 0, 100, '{}')
            """,
            (norm_id, raw_id, url, title, preview_text),
        )
        connection.execute(
            """
            INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
            VALUES (?, NULL, 'fresh', 'keep', 'stored_only', NULL, ?, '{"event_flags": {"deployment_event": true}}', ?, 0, '2026-05-01T00:00:00+00:00')
            """,
            (norm_id, score, summary_text),
        )
    connection.commit()
    connection.close()
    return db_path


def test_open_readonly_connection_uses_sqlite_ro_uri(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = []

    class _FakeConnection:
        row_factory = None

    def _fake_connect(target, uri=False):
        calls.append((target, uri))
        return _FakeConnection()

    monkeypatch.setattr(preview.sqlite3, "connect", _fake_connect)
    preview.open_readonly_connection(tmp_path / "artifact.db")

    assert calls
    assert "mode=ro" in calls[0][0]
    assert calls[0][1] is True


def test_dry_run_writes_preview_markdown_and_sends_nothing(tmp_path: Path) -> None:
    db_path = _create_artifact_db(tmp_path)
    output_path = tmp_path / "preview.md"
    client = _FakeClaudeClient(
        {
            "Teradyne Robotics revenue rises at the start of 2026": ClaudeFinalCardResult(
                send_ok=True,
                reject_reason=None,
                title="Teradyne Robotics posts fourth straight quarter of growth",
                summary="Teradyne Robotics reported $91 million in Q1 2026 revenue, up from $69 million a year earlier. Growth came from Universal Robots and MiR demand across e-commerce, electronics, semiconductors and AI data centers.",
                why_it_matters=None,
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )
        }
    )
    sender = _FakeSender()

    outcomes = preview.run_preview(
        artifact_path=db_path,
        run_id="run-123",
        title_filters=["Teradyne"],
        output_path=output_path,
        send_telegram=False,
        client=client,
        sender=sender,
    )

    assert len(outcomes) == 1
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "<b>Teradyne Robotics posts fourth straight quarter of growth</b>" in content
    assert '<a href="https://www.therobotreport.com/teradyne-robotics-revenue-rises-start-2026/">Link</a>' in content
    assert "The Robot Report" in content
    assert sender.sent_cards == []


def test_send_telegram_requires_preview_only_env_vars(tmp_path: Path) -> None:
    db_path = _create_artifact_db(tmp_path)
    output_path = tmp_path / "preview.md"
    client = _FakeClaudeClient(
        {
            "Teradyne Robotics revenue rises at the start of 2026": ClaudeFinalCardResult(
                send_ok=True,
                reject_reason=None,
                title="Teradyne Robotics posts fourth straight quarter of growth",
                summary="Teradyne Robotics reported $91 million in Q1 2026 revenue, up from $69 million a year earlier. Growth came from Universal Robots and MiR demand across e-commerce, electronics, semiconductors and AI data centers.",
                why_it_matters=None,
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )
        }
    )

    with pytest.raises(SystemExit, match="TELEGRAM_CLAUDE_PREVIEW_BOT_TOKEN"):
        preview.run_preview(
            artifact_path=db_path,
            run_id="run-123",
            title_filters=["Teradyne"],
            output_path=output_path,
            send_telegram=True,
            environ={
                "TELEGRAM_ALERT_BOT_TOKEN": "prod-token",
                "TELEGRAM_ALERT_CHAT_IDS": "111,222",
            },
            client=client,
        )


def test_requested_title_matching_is_case_insensitive(tmp_path: Path) -> None:
    db_path = _create_artifact_db(tmp_path)
    stories = []
    with preview.open_readonly_connection(db_path) as connection:
        stories = preview._load_stories(connection, "run-123", ["launchpad build ai"])

    assert len(stories) == 1
    assert stories[0].title == "Launchpad Build AI offers MLM to speed industrial automation design"


def test_claude_rejection_is_recorded_in_preview_file(tmp_path: Path) -> None:
    db_path = _create_artifact_db(tmp_path)
    output_path = tmp_path / "preview.md"
    client = _FakeClaudeClient(
        {
            "Launchpad Build AI offers MLM to speed industrial automation design": ClaudeFinalCardResult(
                send_ok=False,
                reject_reason="too_generic",
                title=None,
                summary=None,
                why_it_matters=None,
                duplicate_risk="low",
                confidence="medium",
                used_claude=True,
            )
        }
    )

    outcomes = preview.run_preview(
        artifact_path=db_path,
        run_id="run-123",
        title_filters=["Launchpad"],
        output_path=output_path,
        send_telegram=False,
        client=client,
    )

    assert outcomes[0].status == "rejected"
    content = output_path.read_text(encoding="utf-8")
    assert "Status: rejected" in content
    assert "Reason: too_generic" in content


def test_claude_failure_is_recorded_in_preview_file(tmp_path: Path) -> None:
    db_path = _create_artifact_db(tmp_path)
    output_path = tmp_path / "preview.md"
    client = _FakeClaudeClient(
        errors={
            "Launchpad Build AI offers MLM to speed industrial automation design": preview.ClaudeFinalCardUnavailableError(
                "Claude final-card response was not valid JSON."
            )
        }
    )

    outcomes = preview.run_preview(
        artifact_path=db_path,
        run_id="run-123",
        title_filters=["Launchpad"],
        output_path=output_path,
        send_telegram=False,
        client=client,
    )

    assert outcomes[0].status == "failed"
    content = output_path.read_text(encoding="utf-8")
    assert "Status: failed" in content
    assert "Claude final-card response was not valid JSON." in content
