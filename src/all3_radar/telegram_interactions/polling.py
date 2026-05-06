"""Polling runtime for Telegram bot updates."""

from __future__ import annotations

from dataclasses import dataclass

from all3_radar.storage.repositories import RadarRepository
from all3_radar.telegram_interactions.callbacks import (
    TelegramBotApiClient,
    TelegramCallbackResult,
    handle_telegram_callback_update,
)
from all3_radar.telegram_interactions.group_curation import TelegramGroupCurationService

CALLBACK_POLLING_CURSOR_KEY = "telegram_callback_updates"
INTERACTION_POLLING_CURSOR_KEY = "telegram_interaction_updates"


@dataclass(frozen=True)
class TelegramPollingResult:
    fetched_updates: int
    handled_callbacks: int
    next_offset: int | None


@dataclass(frozen=True)
class TelegramInteractionPollingResult:
    fetched_updates: int
    handled_callbacks: int
    stored_messages: int
    stored_reaction_picks: int
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


def poll_telegram_interaction_updates(
    *,
    repository: RadarRepository,
    bot_api_client: TelegramBotApiClient,
    curation_service: TelegramGroupCurationService | None = None,
    limit: int = 50,
    timeout_seconds: int = 0,
) -> TelegramInteractionPollingResult:
    current_cursor = repository.get_integration_cursor(INTERACTION_POLLING_CURSOR_KEY)
    if current_cursor is None:
        current_cursor = repository.get_integration_cursor(CALLBACK_POLLING_CURSOR_KEY)
    offset = int(current_cursor) if current_cursor else None
    allowed_updates = ["callback_query"]
    if curation_service is not None:
        allowed_updates.extend(["message", "channel_post", "message_reaction"])
    updates = bot_api_client.get_updates(
        offset=offset,
        limit=limit,
        timeout_seconds=timeout_seconds,
        allowed_updates=tuple(allowed_updates),
    )

    handled_callbacks = 0
    stored_messages = 0
    stored_reaction_picks = 0
    max_update_id: int | None = None
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)
        callback_result: TelegramCallbackResult = handle_telegram_callback_update(
            update,
            repository=repository,
            bot_api_client=bot_api_client,
        )
        if callback_result.handled:
            handled_callbacks += 1
        if curation_service is not None:
            curation_result = curation_service.ingest_update(update)
            stored_messages += curation_result.stored_messages
            stored_reaction_picks += curation_result.stored_reaction_picks

    next_offset = max_update_id + 1 if max_update_id is not None else offset
    if next_offset is not None:
        repository.upsert_integration_cursor(INTERACTION_POLLING_CURSOR_KEY, str(next_offset))

    return TelegramInteractionPollingResult(
        fetched_updates=len(updates),
        handled_callbacks=handled_callbacks,
        stored_messages=stored_messages,
        stored_reaction_picks=stored_reaction_picks,
        next_offset=next_offset,
    )
