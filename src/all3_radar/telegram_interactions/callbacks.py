"""Handle inbound Telegram callback queries for shortlist actions."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from all3_radar.delivery.telegram import build_inline_reply_markup, build_shortlist_action_button
from all3_radar.editorial_signals.service import EditorialSignalService
from all3_radar.storage.repositories import RadarRepository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramCallbackResult:
    handled: bool
    action: str | None
    normalized_item_id: str | None
    is_active: bool | None
    message: str


class TelegramBotApiClient:
    def __init__(self, bot_token: str | None) -> None:
        self.bot_token = bot_token

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token)

    def _post(self, method: str, payload: dict[str, object]) -> None:
        if not self.is_configured:
            return
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            return

    def _request_json(self, method: str, payload: dict[str, object], *, timeout_seconds: int) -> dict[str, object]:
        if not self.is_configured:
            return {"ok": False, "description": "telegram_not_configured"}
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not isinstance(body, dict):
            return {"ok": False, "description": "telegram_invalid_response_body"}
        return body

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        if not self.is_configured:
            return
        body = self._request_json(
            "deleteWebhook",
            {"drop_pending_updates": bool(drop_pending_updates)},
            timeout_seconds=15,
        )
        if not body.get("ok", False):
            LOGGER.warning("Telegram deleteWebhook failed: %s", body.get("description") or body)

    def get_updates(
        self,
        *,
        offset: int | None = None,
        limit: int = 50,
        timeout_seconds: int = 0,
        allowed_updates: tuple[str, ...] = ("callback_query",),
    ) -> list[dict[str, object]]:
        if not self.is_configured:
            return []
        payload: dict[str, object] = {
            "limit": limit,
            "timeout": timeout_seconds,
            "allowed_updates": list(allowed_updates),
        }
        if offset is not None:
            payload["offset"] = offset
        body = self._request_json(
            "getUpdates",
            payload,
            timeout_seconds=max(timeout_seconds + 5, 10),
        )
        if not body.get("ok", False):
            LOGGER.warning("Telegram getUpdates failed: %s", body.get("description") or body)
            return []
        result = body.get("result", [])
        return [update for update in result if isinstance(update, dict)]

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        self._post(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": text,
            },
        )

    def edit_shortlist_button(
        self,
        chat_id: str,
        telegram_message_id: str,
        *,
        normalized_item_id: str,
        is_active: bool,
    ) -> None:
        self._post(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": int(telegram_message_id),
                "reply_markup": build_inline_reply_markup(
                    (build_shortlist_action_button(normalized_item_id, is_active=is_active),)
                ),
            },
        )


def handle_telegram_callback_update(
    update: dict[str, object],
    *,
    repository: RadarRepository,
    bot_api_client: TelegramBotApiClient,
) -> TelegramCallbackResult:
    callback_query = update.get("callback_query")
    if not isinstance(callback_query, dict):
        return TelegramCallbackResult(False, None, None, None, "No callback_query in update.")

    callback_data = str(callback_query.get("data") or "")
    message = callback_query.get("message") or {}
    from_user = callback_query.get("from") or {}
    chat = message.get("chat") if isinstance(message, dict) else {}
    if not isinstance(chat, dict):
        chat = {}

    chat_id = str(chat.get("id") or "")
    telegram_message_id = str(message.get("message_id") or "")
    user_id = str(from_user.get("id") or "")
    username = str(from_user.get("username") or "")
    callback_query_id = str(callback_query.get("id") or "")

    if callback_data.startswith("shortlist:toggle:"):
        normalized_item_id = callback_data.removeprefix("shortlist:toggle:")

        mapping = repository.get_item_event_mapping(normalized_item_id)
        canonical_event_id = mapping["canonical_event_id"] if mapping else None

        signal_service = EditorialSignalService(repository)
        result = signal_service.toggle_shortlist(
            normalized_item_id=normalized_item_id,
            canonical_event_id=canonical_event_id,
            chat_id=chat_id,
            telegram_message_id=telegram_message_id,
            user_id=user_id,
            username=username,
        )

        response_text = "Added to shortlist" if result.is_active else "Removed from shortlist"
        if callback_query_id:
            try:
                bot_api_client.answer_callback_query(callback_query_id, response_text)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
        if chat_id and telegram_message_id:
            try:
                bot_api_client.edit_shortlist_button(
                    chat_id,
                    telegram_message_id,
                    normalized_item_id=normalized_item_id,
                    is_active=result.is_active,
                )
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
                pass

        return TelegramCallbackResult(
            handled=True,
            action="shortlist_toggle",
            normalized_item_id=normalized_item_id,
            is_active=result.is_active,
            message=response_text,
        )

    if callback_data.startswith("digest_vote:toggle:"):
        parts = callback_data.split(":", 3)
        if len(parts) != 4:
            return TelegramCallbackResult(False, None, None, None, "Unsupported callback action.")
        _, _, vote_round_id, canonical_event_id = parts
        vote_round = repository.get_digest_vote_round(vote_round_id)
        if vote_round is None or str(vote_round.get("status") or "").lower() == "closed":
            response_text = "Voting is closed."
            if callback_query_id:
                try:
                    bot_api_client.answer_callback_query(callback_query_id, response_text)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    pass
            return TelegramCallbackResult(True, "digest_vote_toggle", None, False, response_text)
        if not repository.has_digest_vote_candidate(vote_round_id, canonical_event_id):
            return TelegramCallbackResult(False, None, None, None, "Unsupported callback action.")

        current_state = repository.get_digest_vote_state(
            vote_round_id=vote_round_id,
            canonical_event_id=canonical_event_id,
            voter_user_id=user_id,
            actor_chat_id="",
        )
        seats_to_fill = int(vote_round.get("seats_to_fill") or 0)
        if not current_state:
            active_votes = repository.count_active_digest_votes_for_voter(
                vote_round_id=vote_round_id,
                voter_user_id=user_id,
                actor_chat_id="",
            )
            if seats_to_fill > 0 and active_votes >= seats_to_fill:
                response_text = f"You can vote for up to {seats_to_fill} stor{'y' if seats_to_fill == 1 else 'ies'}."
                if callback_query_id:
                    try:
                        bot_api_client.answer_callback_query(callback_query_id, response_text)
                    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                        pass
                return TelegramCallbackResult(True, "digest_vote_toggle", None, False, response_text)

        next_state = not current_state
        repository.upsert_digest_vote(
            vote_round_id=vote_round_id,
            canonical_event_id=canonical_event_id,
            voter_user_id=user_id,
            actor_chat_id="",
            is_active=next_state,
        )
        active_votes = repository.count_active_digest_votes_for_voter(
            vote_round_id=vote_round_id,
            voter_user_id=user_id,
            actor_chat_id="",
        )
        response_text = (
            f"Vote saved ({active_votes}/{seats_to_fill})"
            if next_state
            else f"Vote removed ({active_votes}/{seats_to_fill})"
        )
        if callback_query_id:
            try:
                bot_api_client.answer_callback_query(callback_query_id, response_text)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
        return TelegramCallbackResult(True, "digest_vote_toggle", None, next_state, response_text)

    return TelegramCallbackResult(False, None, None, None, "Unsupported callback action.")
