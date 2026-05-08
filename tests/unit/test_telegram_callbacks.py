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
