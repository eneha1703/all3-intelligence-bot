import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository
from all3_radar.telegram_interactions.callbacks import TelegramBotApiClient
from all3_radar.telegram_interactions.polling import (
    CALLBACK_POLLING_CURSOR_KEY,
    poll_telegram_callback_updates,
)


def _seed_db(db_path: Path, schema_path: Path) -> RadarRepository:
    initialize_database(db_path, schema_path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "item-1",
                "raw-1",
                "robot_report_rss",
                "https://example.com/story",
                "example.com",
                "Test story",
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
            ("event-1", "item-1", "event-1", "Test story", now, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "item-1",
                "event-1",
                "fresh",
                "keep",
                "sent",
                None,
                50,
                "{}",
                "Summary",
                0,
                now,
            ),
        )
        connection.commit()
    return RadarRepository(db_path)


class _FakePollingBotApiClient(TelegramBotApiClient):
    def __init__(self, updates: list[dict[str, object]]) -> None:
        super().__init__(bot_token="token")
        self.updates = updates
        self.get_updates_calls: list[tuple[int | None, int, int, tuple[str, ...]]] = []
        self.callback_answers: list[tuple[str, str]] = []
        self.button_updates: list[tuple[str, str, str, bool]] = []

    def get_updates(
        self,
        *,
        offset: int | None = None,
        limit: int = 50,
        timeout_seconds: int = 0,
        allowed_updates: tuple[str, ...] = ("callback_query",),
    ) -> list[dict[str, object]]:
        self.get_updates_calls.append((offset, limit, timeout_seconds, allowed_updates))
        return self.updates

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        return

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


def test_polling_worker_processes_callback_updates_and_advances_cursor(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = _seed_db(tmp_path / "polling.db", repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
    api_client = _FakePollingBotApiClient(
        [
            {
                "update_id": 501,
                "callback_query": {
                    "id": "cb-1",
                    "data": "shortlist:toggle:item-1",
                    "from": {"id": 42, "username": "editor"},
                    "message": {"message_id": 99, "chat": {"id": 1001}},
                },
            }
        ]
    )

    result = poll_telegram_callback_updates(
        repository=repository,
        bot_api_client=api_client,
        limit=10,
        timeout_seconds=2,
    )

    assert result.fetched_updates == 1
    assert result.handled_callbacks == 1
    assert result.next_offset == 502
    assert api_client.get_updates_calls == [(None, 10, 2, ("callback_query",))]
    assert api_client.callback_answers == [("cb-1", "Added to shortlist")]
    assert api_client.button_updates == [("1001", "99", "item-1", True)]
    assert repository.get_integration_cursor(CALLBACK_POLLING_CURSOR_KEY) == "502"


def test_polling_worker_uses_stored_cursor_on_next_call(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = _seed_db(tmp_path / "polling.db", repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
    repository.upsert_integration_cursor(CALLBACK_POLLING_CURSOR_KEY, "700")
    api_client = _FakePollingBotApiClient([])

    result = poll_telegram_callback_updates(
        repository=repository,
        bot_api_client=api_client,
        limit=5,
        timeout_seconds=0,
    )

    assert result.fetched_updates == 0
    assert result.handled_callbacks == 0
    assert result.next_offset == 700
    assert api_client.get_updates_calls == [(700, 5, 0, ("callback_query",))]
    assert repository.get_integration_cursor(CALLBACK_POLLING_CURSOR_KEY) == "700"
