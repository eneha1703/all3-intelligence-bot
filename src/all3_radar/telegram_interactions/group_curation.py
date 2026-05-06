"""Group message and reaction ingestion for Telegram shortlist curation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from all3_radar.storage.repositories import RadarRepository

URL_RE = re.compile(r"https?://[^\s<>\")\]]+")

EMOJI_REACTION_ALIASES = {
    "\u2b50": "emoji:star",
    "\U0001f525": "emoji:fire",
    "\u2705": "emoji:white_check_mark",
    "\U0001f44d": "emoji:thumbs_up",
}


@dataclass(frozen=True)
class TelegramGroupMessageRecord:
    chat_id: str
    telegram_message_id: str
    sent_by_bot: bool
    sender_user_id: str
    sender_chat_id: str
    message_ts: str
    message_text: str | None
    message_caption: str | None
    message_urls: tuple[str, ...]
    has_links: bool
    raw_update: dict[str, Any]


@dataclass(frozen=True)
class TelegramReactionPickRecord:
    chat_id: str
    telegram_message_id: str
    reactor_user_id: str
    actor_chat_id: str
    reaction_key: str
    is_active: bool
    picked_at: str
    source_update_kind: str
    raw_update: dict[str, Any]


@dataclass(frozen=True)
class TelegramGroupCurationResult:
    handled: bool
    stored_messages: int
    stored_reaction_picks: int


def _telegram_ts_to_iso(value: Any) -> str:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    if isinstance(value, str) and value.strip().isdigit():
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _string_id(value: Any) -> str:
    return str(value) if value is not None else ""


def _extract_urls(text: str | None, entities: Any) -> list[str]:
    urls: list[str] = []
    if text:
        urls.extend(URL_RE.findall(text))
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_url = entity.get("url")
            if entity.get("type") == "text_link" and isinstance(entity_url, str) and entity_url:
                urls.append(entity_url)
    return urls


def _dedupe_urls(urls: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = url.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def _first_message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("message", "channel_post"):
        message = update.get(key)
        if isinstance(message, dict):
            return message
    return None


def parse_group_message_update(update: dict[str, Any]) -> TelegramGroupMessageRecord | None:
    message = _first_message_from_update(update)
    if message is None:
        return None

    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = _string_id(chat.get("id"))
    telegram_message_id = _string_id(message.get("message_id"))
    if not chat_id or not telegram_message_id:
        return None

    from_user = message.get("from")
    if not isinstance(from_user, dict):
        from_user = {}
    sender_chat = message.get("sender_chat")
    if not isinstance(sender_chat, dict):
        sender_chat = {}

    text = message.get("text") if isinstance(message.get("text"), str) else None
    caption = message.get("caption") if isinstance(message.get("caption"), str) else None
    urls = _dedupe_urls(
        [
            *_extract_urls(text, message.get("entities")),
            *_extract_urls(caption, message.get("caption_entities")),
        ]
    )
    sent_by_bot = bool(from_user.get("is_bot"))

    # User-authored text-only chatter should not become shortlist material.
    if not sent_by_bot and not urls:
        return None

    return TelegramGroupMessageRecord(
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        sent_by_bot=sent_by_bot,
        sender_user_id=_string_id(from_user.get("id")),
        sender_chat_id=_string_id(sender_chat.get("id")),
        message_ts=_telegram_ts_to_iso(message.get("date")),
        message_text=text,
        message_caption=caption,
        message_urls=urls,
        has_links=bool(urls),
        raw_update=update,
    )


def normalize_reaction_key(reaction: dict[str, Any]) -> str | None:
    reaction_type = reaction.get("type")
    if reaction_type == "emoji":
        emoji = reaction.get("emoji")
        if not isinstance(emoji, str) or not emoji:
            return None
        return EMOJI_REACTION_ALIASES.get(emoji, f"emoji:{emoji}")
    if reaction_type == "custom_emoji":
        custom_emoji_id = reaction.get("custom_emoji_id")
        if custom_emoji_id is None:
            return None
        return f"custom_emoji:{custom_emoji_id}"
    if reaction_type == "paid":
        return "paid"
    return None


def _reaction_keys(reactions: Any) -> set[str]:
    if not isinstance(reactions, list):
        return set()
    keys: set[str] = set()
    for reaction in reactions:
        if not isinstance(reaction, dict):
            continue
        reaction_key = normalize_reaction_key(reaction)
        if reaction_key:
            keys.add(reaction_key)
    return keys


def parse_reaction_pick_updates(
    update: dict[str, Any],
    *,
    allowed_reaction_keys: tuple[str, ...],
) -> list[TelegramReactionPickRecord]:
    message_reaction = update.get("message_reaction")
    if not isinstance(message_reaction, dict):
        return []

    chat = message_reaction.get("chat")
    if not isinstance(chat, dict):
        return []
    chat_id = _string_id(chat.get("id"))
    telegram_message_id = _string_id(message_reaction.get("message_id"))
    if not chat_id or not telegram_message_id:
        return []

    allowed = set(allowed_reaction_keys)
    old_keys = _reaction_keys(message_reaction.get("old_reaction"))
    new_keys = _reaction_keys(message_reaction.get("new_reaction"))
    relevant_keys = (old_keys | new_keys) & allowed
    if not relevant_keys:
        return []

    user = message_reaction.get("user")
    if not isinstance(user, dict):
        user = {}
    actor_chat = message_reaction.get("actor_chat")
    if not isinstance(actor_chat, dict):
        actor_chat = {}

    picked_at = _telegram_ts_to_iso(message_reaction.get("date"))
    return [
        TelegramReactionPickRecord(
            chat_id=chat_id,
            telegram_message_id=telegram_message_id,
            reactor_user_id=_string_id(user.get("id")),
            actor_chat_id=_string_id(actor_chat.get("id")),
            reaction_key=reaction_key,
            is_active=reaction_key in new_keys,
            picked_at=picked_at,
            source_update_kind="message_reaction",
            raw_update=update,
        )
        for reaction_key in sorted(relevant_keys)
    ]


class TelegramGroupCurationService:
    def __init__(
        self,
        repository: RadarRepository,
        *,
        enabled: bool,
        message_ingest_enabled: bool,
        reaction_shortlist_enabled: bool,
        allowed_reaction_keys: tuple[str, ...],
    ) -> None:
        self.repository = repository
        self.enabled = enabled
        self.message_ingest_enabled = message_ingest_enabled
        self.reaction_shortlist_enabled = reaction_shortlist_enabled
        self.allowed_reaction_keys = allowed_reaction_keys

    def ingest_update(self, update: dict[str, Any]) -> TelegramGroupCurationResult:
        if not self.enabled:
            return TelegramGroupCurationResult(False, 0, 0)

        stored_messages = 0
        stored_reaction_picks = 0

        if self.message_ingest_enabled:
            message_record = parse_group_message_update(update)
            if message_record is not None:
                self.repository.upsert_telegram_group_message(
                    chat_id=message_record.chat_id,
                    telegram_message_id=message_record.telegram_message_id,
                    sent_by_bot=message_record.sent_by_bot,
                    sender_user_id=message_record.sender_user_id,
                    sender_chat_id=message_record.sender_chat_id,
                    message_ts=message_record.message_ts,
                    message_text=message_record.message_text,
                    message_caption=message_record.message_caption,
                    message_urls=message_record.message_urls,
                    has_links=message_record.has_links,
                    raw_update=message_record.raw_update,
                )
                stored_messages = 1

        if self.reaction_shortlist_enabled:
            reaction_records = parse_reaction_pick_updates(
                update,
                allowed_reaction_keys=self.allowed_reaction_keys,
            )
            for reaction_record in reaction_records:
                self.repository.upsert_telegram_reaction_pick(
                    chat_id=reaction_record.chat_id,
                    telegram_message_id=reaction_record.telegram_message_id,
                    reactor_user_id=reaction_record.reactor_user_id,
                    actor_chat_id=reaction_record.actor_chat_id,
                    reaction_key=reaction_record.reaction_key,
                    is_active=reaction_record.is_active,
                    picked_at=reaction_record.picked_at,
                    source_update_kind=reaction_record.source_update_kind,
                    raw_update=reaction_record.raw_update,
                )
            stored_reaction_picks = len(reaction_records)

        return TelegramGroupCurationResult(
            handled=bool(stored_messages or stored_reaction_picks),
            stored_messages=stored_messages,
            stored_reaction_picks=stored_reaction_picks,
        )
