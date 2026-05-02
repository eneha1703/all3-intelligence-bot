"""Polling runtime for Telegram bot updates."""

from __future__ import annotations

from dataclasses import dataclass

from all3_radar.storage.repositories import RadarRepository
from all3_radar.telegram_interactions.callbacks import (
    TelegramBotApiClient,
    TelegramCallbackResult,
    handle_telegram_callback_update,
)

CALLBACK_POLLING_CURSOR_KEY = "telegram_callback_updates"


@dataclass(frozen=True)
class TelegramPollingResult:
    fetched_updates: int
    handled_callbacks: int
    next_offset: int | None


def poll_telegram_callback_updates(
    *,
    repository: RadarRepository,
    bot_api_client: TelegramBotApiClient,
    limit: int = 50,
    timeout_seconds: int = 0,
) -> TelegramPollingResult:
    current_cursor = repository.get_integration_cursor(CALLBACK_POLLING_CURSOR_KEY)
    offset = int(current_cursor) if current_cursor else None
    updates = bot_api_client.get_updates(
        offset=offset,
        limit=limit,
        timeout_seconds=timeout_seconds,
        allowed_updates=("callback_query",),
    )

    handled_callbacks = 0
    max_update_id: int | None = None
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)
        result: TelegramCallbackResult = handle_telegram_callback_update(
            update,
            repository=repository,
            bot_api_client=bot_api_client,
        )
        if result.handled:
            handled_callbacks += 1

    next_offset = max_update_id + 1 if max_update_id is not None else offset
    if next_offset is not None:
        repository.upsert_integration_cursor(CALLBACK_POLLING_CURSOR_KEY, str(next_offset))

    return TelegramPollingResult(
        fetched_updates=len(updates),
        handled_callbacks=handled_callbacks,
        next_offset=next_offset,
    )
