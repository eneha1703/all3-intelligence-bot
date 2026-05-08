import sqlite3
from pathlib import Path

from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository
from all3_radar.telegram_interactions.group_curation import (
    TelegramGroupCurationService,
    normalize_reaction_key,
    parse_group_message_update,
)
from all3_radar.telegram_interactions.callbacks import TelegramBotApiClient
from all3_radar.telegram_interactions.polling import (
    CALLBACK_POLLING_CURSOR_KEY,
    INTERACTION_POLLING_CURSOR_KEY,
    poll_telegram_interaction_updates,
)


def _repository(tmp_path: Path) -> RadarRepository:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "telegram_group_curation.db"
    initialize_database(db_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
    return RadarRepository(db_path)


def _seed_digest_item(
    repository: RadarRepository,
    *,
    canonical_url: str = "https://example.com/robotics-factory",
    item_suffix: str = "1",
) -> None:
    now = "2026-05-01T12:00:00+00:00"
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"item-{item_suffix}",
                f"raw-{item_suffix}",
                "telegram_matched_source",
                canonical_url,
                "example.com",
                "Robotics factory deployment",
                None,
                "A robotics factory deployment with physical industry relevance.",
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
            (
                f"event-{item_suffix}",
                f"item-{item_suffix}",
                f"event-{item_suffix}",
                "Robotics factory deployment",
                now,
                now,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"item-{item_suffix}",
                f"event-{item_suffix}",
                "fresh",
                "keep",
                "sent",
                None,
                90,
                '{"event_flags":{"industrial_robotics_signal":true}}',
                "A matched digest candidate.",
                0,
                now,
            ),
        )
        connection.commit()


def _enabled_service(repository: RadarRepository, allowed: tuple[str, ...] = ("emoji:star",)) -> TelegramGroupCurationService:
    return TelegramGroupCurationService(
        repository,
        enabled=True,
        message_ingest_enabled=True,
        reaction_shortlist_enabled=True,
        allowed_reaction_keys=allowed,
    )


def _message_update(message_id: int = 77) -> dict[str, object]:
    return {
        "update_id": 1001,
        "message": {
            "message_id": message_id,
            "date": 1_777_636_800,
            "chat": {"id": -100123, "type": "supergroup"},
            "from": {"id": 42, "is_bot": False, "username": "reader"},
            "text": "Worth saving: https://example.com/robotics-factory",
            "entities": [{"type": "url", "offset": 14, "length": 36}],
        },
    }


def _star_reaction_update(message_id: int = 77, *, active: bool = True, update_id: int = 1002) -> dict[str, object]:
    old_reaction = [] if active else [{"type": "emoji", "emoji": "\u2b50"}]
    new_reaction = [{"type": "emoji", "emoji": "\u2b50"}] if active else []
    return {
        "update_id": update_id,
        "message_reaction": {
            "chat": {"id": -100123, "type": "supergroup"},
            "message_id": message_id,
            "user": {"id": 42, "is_bot": False},
            "date": 1_777_636_830,
            "old_reaction": old_reaction,
            "new_reaction": new_reaction,
        },
    }


def test_parse_group_message_update_accepts_user_news_link() -> None:
    record = parse_group_message_update(_message_update())

    assert record is not None
    assert record.chat_id == "-100123"
    assert record.telegram_message_id == "77"
    assert record.sent_by_bot is False
    assert record.sender_user_id == "42"
    assert record.message_urls == ("https://example.com/robotics-factory",)
    assert record.has_links is True


def test_group_curation_service_stores_user_news_links(tmp_path) -> None:
    repository = _repository(tmp_path)
    result = _enabled_service(repository).ingest_update(_message_update())

    with sqlite3.connect(repository.database_path) as connection:
        row = connection.execute("SELECT * FROM telegram_group_messages").fetchone()

    assert result.handled is True
    assert result.stored_messages == 1
    assert row[1] == "-100123"
    assert row[2] == "77"
    assert row[7] == "Worth saving: https://example.com/robotics-factory"
    assert row[9] == "https://example.com/robotics-factory"
    assert row[10] == 1
    assert row[11] == 1


def test_group_curation_stores_multiple_links_without_picking_one_as_message_url(tmp_path) -> None:
    repository = _repository(tmp_path)
    update = _message_update()
    message = dict(update["message"])  # type: ignore[index]
    message["text"] = "Two links https://example.com/one and https://example.com/two"
    message["entities"] = [
        {"type": "url", "offset": 10, "length": 23},
        {"type": "url", "offset": 38, "length": 23},
    ]

    result = _enabled_service(repository).ingest_update({**update, "message": message})

    with sqlite3.connect(repository.database_path) as connection:
        group_row = connection.execute(
            "SELECT message_url, has_links, link_count FROM telegram_group_messages WHERE telegram_message_id = '77'"
        ).fetchone()
        link_rows = connection.execute(
            """
            SELECT link_index, url
            FROM telegram_group_message_links
            WHERE chat_id = '-100123' AND telegram_message_id = '77'
            ORDER BY link_index
            """
        ).fetchall()

    assert result.handled is True
    assert group_row == (None, 1, 2)
    assert link_rows == [
        (0, "https://example.com/one"),
        (1, "https://example.com/two"),
    ]


def test_group_curation_ignores_user_text_without_links(tmp_path) -> None:
    repository = _repository(tmp_path)
    update = _message_update()
    message = dict(update["message"])  # type: ignore[index]
    message["text"] = "Interesting, let's discuss this later"
    message["entities"] = []

    result = _enabled_service(repository).ingest_update({**update, "message": message})

    with sqlite3.connect(repository.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM telegram_group_messages").fetchone()[0]

    assert result.handled is False
    assert count == 0


def test_group_curation_can_be_disabled_independently(tmp_path) -> None:
    repository = _repository(tmp_path)
    service = TelegramGroupCurationService(
        repository,
        enabled=False,
        message_ingest_enabled=True,
        reaction_shortlist_enabled=True,
        allowed_reaction_keys=("emoji:star",),
    )

    result = service.ingest_update(_message_update())

    with sqlite3.connect(repository.database_path) as connection:
        message_count = connection.execute("SELECT COUNT(*) FROM telegram_group_messages").fetchone()[0]
        reaction_count = connection.execute("SELECT COUNT(*) FROM telegram_reaction_picks").fetchone()[0]

    assert result.handled is False
    assert message_count == 0
    assert reaction_count == 0


def test_allowed_reaction_adds_and_removes_shortlist_candidate(tmp_path) -> None:
    repository = _repository(tmp_path)
    service = _enabled_service(repository)
    service.ingest_update(_message_update())

    add_result = service.ingest_update(_star_reaction_update(active=True))
    active_candidates = repository.load_telegram_reaction_shortlist_candidates(
        window_start="2026-01-01T00:00:00+00:00",
        window_end="2026-12-31T23:59:59+00:00",
        allowed_reaction_keys=("emoji:star",),
        min_unique_reactors=1,
        limit=10,
    )

    remove_result = service.ingest_update(_star_reaction_update(active=False, update_id=1003))
    inactive_candidates = repository.load_telegram_reaction_shortlist_candidates(
        window_start="2026-01-01T00:00:00+00:00",
        window_end="2026-12-31T23:59:59+00:00",
        allowed_reaction_keys=("emoji:star",),
        min_unique_reactors=1,
        limit=10,
    )

    with sqlite3.connect(repository.database_path) as connection:
        row = connection.execute(
            "SELECT reaction_key, is_active FROM telegram_reaction_picks WHERE telegram_message_id = '77'"
        ).fetchone()

    assert add_result.stored_reaction_picks == 1
    assert active_candidates[0]["telegram_message_id"] == "77"
    assert active_candidates[0]["message_url"] == "https://example.com/robotics-factory"
    assert remove_result.stored_reaction_picks == 1
    assert inactive_candidates == []
    assert row == ("emoji:star", 0)


def test_reaction_digest_candidates_include_user_posted_links_when_matched(tmp_path) -> None:
    repository = _repository(tmp_path)
    _seed_digest_item(repository)
    service = _enabled_service(repository)
    service.ingest_update(_message_update())
    service.ingest_update(_star_reaction_update(active=True))

    rows = repository.load_telegram_reaction_digest_candidates_for_week(
        start_date="2026-04-30",
        end_date="2026-05-07",
        allowed_reaction_keys=("emoji:star",),
        min_unique_reactors=1,
        limit=10,
        require_canonical_events=True,
    )

    assert len(rows) == 1
    assert rows[0]["canonical_event_id"] == "event-1"
    assert rows[0]["normalized_item_id"] == "item-1"
    assert rows[0]["canonical_url"] == "https://example.com/robotics-factory"
    assert rows[0]["unique_reactors"] == 1


def test_reaction_digest_candidates_include_bot_delivered_messages_without_group_message(tmp_path) -> None:
    repository = _repository(tmp_path)
    _seed_digest_item(repository)
    repository.upsert_telegram_reaction_pick(
        chat_id="-100123",
        telegram_message_id="88",
        reactor_user_id="42",
        actor_chat_id="",
        reaction_key="emoji:star",
        is_active=True,
        picked_at="2026-05-01T12:30:00+00:00",
        source_update_kind="message_reaction",
        raw_update={},
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO telegram_deliveries (id, bot_kind, run_id, normalized_item_id, canonical_event_id, chat_id, telegram_message_id, status, payload_text, error_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "delivery-1",
                "alert",
                "run-1",
                "item-1",
                "event-1",
                "-100123",
                "88",
                "sent",
                "Payload",
                None,
                "2026-05-01T12:00:00+00:00",
            ),
        )
        connection.commit()

    rows = repository.load_telegram_reaction_digest_candidates_for_week(
        start_date="2026-04-30",
        end_date="2026-05-07",
        allowed_reaction_keys=("emoji:star",),
        min_unique_reactors=1,
        limit=10,
        require_canonical_events=True,
    )

    assert len(rows) == 1
    assert rows[0]["canonical_event_id"] == "event-1"
    assert rows[0]["normalized_item_id"] == "item-1"
    assert rows[0]["title"] == "Robotics factory deployment"


def test_reaction_digest_candidates_skip_ambiguous_multi_link_user_message(tmp_path) -> None:
    repository = _repository(tmp_path)
    _seed_digest_item(repository, canonical_url="https://example.com/one", item_suffix="1")
    _seed_digest_item(repository, canonical_url="https://example.com/two", item_suffix="2")
    service = _enabled_service(repository)

    update = _message_update()
    message = dict(update["message"])  # type: ignore[index]
    message["text"] = "Two links https://example.com/one and https://example.com/two"
    message["entities"] = [
        {"type": "url", "offset": 10, "length": 23},
        {"type": "url", "offset": 38, "length": 23},
    ]
    service.ingest_update({**update, "message": message})
    service.ingest_update(_star_reaction_update(active=True))

    rows = repository.load_telegram_reaction_digest_candidates_for_week(
        start_date="2026-04-30",
        end_date="2026-05-07",
        allowed_reaction_keys=("emoji:star",),
        min_unique_reactors=1,
        limit=10,
        require_canonical_events=False,
    )

    assert rows == []


def test_reactions_outside_allowlist_do_not_create_picks(tmp_path) -> None:
    repository = _repository(tmp_path)
    service = _enabled_service(repository, allowed=("emoji:star",))
    update = {
        "message_reaction": {
            "chat": {"id": -100123},
            "message_id": 77,
            "user": {"id": 42},
            "date": 1_777_636_830,
            "old_reaction": [],
            "new_reaction": [{"type": "emoji", "emoji": "\U0001f525"}],
        }
    }

    result = service.ingest_update(update)

    with sqlite3.connect(repository.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM telegram_reaction_picks").fetchone()[0]

    assert normalize_reaction_key({"type": "emoji", "emoji": "\U0001f525"}) == "emoji:fire"
    assert result.handled is False
    assert count == 0


class _FakeGroupPollingBotApiClient(TelegramBotApiClient):
    def __init__(self, updates: list[dict[str, object]]) -> None:
        super().__init__(bot_token="token")
        self.updates = updates
        self.get_updates_calls: list[tuple[int | None, int, int, tuple[str, ...]]] = []

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


def test_interaction_polling_handles_group_curation_with_one_shared_cursor(tmp_path) -> None:
    repository = _repository(tmp_path)
    service = _enabled_service(repository)
    api_client = _FakeGroupPollingBotApiClient(
        [
            _message_update(),
            _star_reaction_update(update_id=1002),
        ]
    )

    result = poll_telegram_interaction_updates(
        repository=repository,
        bot_api_client=api_client,
        curation_service=service,
        limit=25,
        timeout_seconds=3,
    )

    assert result.fetched_updates == 2
    assert result.handled_callbacks == 0
    assert result.stored_messages == 1
    assert result.stored_reaction_picks == 1
    assert result.next_offset == 1003
    assert api_client.get_updates_calls == [
        (None, 25, 3, ("callback_query", "message", "channel_post", "message_reaction"))
    ]
    assert repository.get_integration_cursor(INTERACTION_POLLING_CURSOR_KEY) == "1003"


def test_interaction_polling_migrates_existing_callback_cursor(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.upsert_integration_cursor(CALLBACK_POLLING_CURSOR_KEY, "900")
    service = _enabled_service(repository)
    api_client = _FakeGroupPollingBotApiClient([])

    result = poll_telegram_interaction_updates(
        repository=repository,
        bot_api_client=api_client,
        curation_service=service,
        limit=25,
        timeout_seconds=0,
    )

    assert result.next_offset == 900
    assert api_client.get_updates_calls == [
        (900, 25, 0, ("callback_query", "message", "channel_post", "message_reaction"))
    ]
    assert repository.get_integration_cursor(INTERACTION_POLLING_CURSOR_KEY) == "900"
