import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository
from all3_radar.telegram_interactions.callbacks import (
    TelegramCallbackResult,
    TelegramBotApiClient,
    handle_telegram_callback_update,
)


def _seed_db(db_path: Path, schema_path: Path) -> RadarRepository:
    initialize_database(db_path, schema_path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs (id, pipeline, started_at, finished_at, status, config_snapshot_json, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("pipeline-1", "digest", now, now, "completed", "{}", "{}"),
        )
        for item_id, raw_id, event_id, url, title, score in (
            ("item-1", "raw-1", "event-1", "https://example.com/story", "Test story", 50),
            ("item-2", "raw-2", "event-2", "https://example.com/story-2", "Second story", 49),
        ):
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
                    "Preview",
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
                INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, item_id, event_id, title, now, now, now, now),
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
                    "sent",
                    None,
                    score,
                    "{}",
                    "Summary",
                    0,
                    now,
                ),
            )
        connection.commit()
    return RadarRepository(db_path)


class _FakeBotApiClient(TelegramBotApiClient):
    def __init__(self) -> None:
        super().__init__(bot_token="token")
        self.callback_answers: list[tuple[str, str]] = []
        self.button_updates: list[tuple[str, str, str, bool]] = []

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        self.callback_answers.append((callback_query_id, text))

    def edit_shortlist_button(
        self,
        chat_id: str,
        telegram_message_id: str,
        *,
        normalized_item_id: str,
        is_active: bool,
    ) -> None:
        self.button_updates.append((chat_id, telegram_message_id, normalized_item_id, is_active))


def test_callback_handler_toggles_shortlist_signal_on_and_off(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = _seed_db(tmp_path / "callbacks.db", repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
    api_client = _FakeBotApiClient()
    update = {
        "callback_query": {
            "id": "cb-1",
            "data": "shortlist:toggle:item-1",
            "from": {"id": 42, "username": "editor"},
            "message": {"message_id": 99, "chat": {"id": 1001}},
        }
    }

    first = handle_telegram_callback_update(update, repository=repository, bot_api_client=api_client)
    second = handle_telegram_callback_update(update, repository=repository, bot_api_client=api_client)

    assert first.handled is True
    assert first.action == "shortlist_toggle"
    assert first.normalized_item_id == "item-1"
    assert first.is_active is True
    assert first.message == "Added to shortlist"

    assert second.handled is True
    assert second.is_active is False
    assert second.message == "Removed from shortlist"

    assert api_client.callback_answers == [
        ("cb-1", "Added to shortlist"),
        ("cb-1", "Removed from shortlist"),
    ]
    assert api_client.button_updates == [
        ("1001", "99", "item-1", True),
        ("1001", "99", "item-1", False),
    ]


def test_callback_handler_ignores_non_shortlist_callbacks(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = _seed_db(tmp_path / "callbacks.db", repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
    api_client = _FakeBotApiClient()
    update = {"callback_query": {"id": "cb-2", "data": "noop:item-1"}}

    result = handle_telegram_callback_update(update, repository=repository, bot_api_client=api_client)

    assert result == TelegramCallbackResult(
        handled=False,
        action=None,
        normalized_item_id=None,
        is_active=None,
        message="Unsupported callback action.",
    )
    assert api_client.callback_answers == []
    assert api_client.button_updates == []


def test_callback_handler_toggles_digest_vote_and_enforces_limit(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = _seed_db(tmp_path / "callbacks.db", repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
    api_client = _FakeBotApiClient()
    round_id = repository.create_digest_vote_round(
        pipeline_run_id="pipeline-1",
        week_key="2026-W18",
        seats_to_fill=1,
        shortlisted_count=4,
        candidate_count=2,
        summary_json="{}",
    )
    repository.replace_digest_vote_candidates(
        round_id,
        shortlisted_candidates=[],
        vote_candidates=[
            {
                "canonical_event_id": "event-1",
                "normalized_item_id": "item-1",
                "source_id": "robot_report_rss",
                "title": "Test story",
                "canonical_url": "https://example.com/story",
                "published_ts": "2026-05-01T00:00:00+00:00",
                "score": 50,
            },
            {
                "canonical_event_id": "event-2",
                "normalized_item_id": "item-2",
                "source_id": "robot_report_rss",
                "title": "Second story",
                "canonical_url": "https://example.com/story-2",
                "published_ts": "2026-05-01T00:00:00+00:00",
                "score": 49,
            },
        ],
    )

    first_update = {
        "callback_query": {
            "id": "cb-3",
            "data": f"digest_vote:toggle:{round_id}:event-1",
            "from": {"id": 42, "username": "editor"},
            "message": {"message_id": 100, "chat": {"id": 1001}},
        }
    }
    second_update = {
        "callback_query": {
            "id": "cb-4",
            "data": f"digest_vote:toggle:{round_id}:event-2",
            "from": {"id": 42, "username": "editor"},
            "message": {"message_id": 100, "chat": {"id": 1001}},
        }
    }

    first = handle_telegram_callback_update(first_update, repository=repository, bot_api_client=api_client)
    blocked = handle_telegram_callback_update(second_update, repository=repository, bot_api_client=api_client)
    removed = handle_telegram_callback_update(first_update, repository=repository, bot_api_client=api_client)

    assert first.handled is True
    assert first.action == "digest_vote_toggle"
    assert first.is_active is True
    assert first.message == "Vote saved (1/1)"

    assert blocked.handled is True
    assert blocked.action == "digest_vote_toggle"
    assert blocked.is_active is False
    assert blocked.message == "You can vote for up to 1 story."

    assert removed.handled is True
    assert removed.is_active is False
    assert removed.message == "Vote removed (0/1)"

    assert api_client.callback_answers == [
        ("cb-3", "Vote saved (1/1)"),
        ("cb-4", "You can vote for up to 1 story."),
        ("cb-3", "Vote removed (0/1)"),
    ]
    assert api_client.button_updates == []
