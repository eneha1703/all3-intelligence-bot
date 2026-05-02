"""Telegram delivery for Bot 1."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from all3_radar.domain.models import TelegramActionButton, TelegramCard
from all3_radar.summarization.fallback_summary import sanitize_summary_text

WHITESPACE_RE = re.compile(r"\s+")


def _normalize_card_summary(headline: str, summary_text: str) -> str | None:
    sanitized = sanitize_summary_text(headline, summary_text)
    if sanitized:
        return sanitized

    normalized = WHITESPACE_RE.sub(" ", summary_text).strip()
    if not normalized:
        return None
    if normalized.lower().startswith(headline.strip().lower()):
        normalized = normalized[len(headline.strip()) :].lstrip(" .:-")
    normalized = WHITESPACE_RE.sub(" ", normalized).strip()
    if len(normalized.split()) < 6:
        return None
    if normalized[-1] not in ".!?":
        normalized = f"{normalized}."
    return normalized or None


def build_shortlist_action_button(normalized_item_id: str, *, is_active: bool = False) -> TelegramActionButton:
    return TelegramActionButton(
        text="✅ Shortlisted" if is_active else "🏆 Add to shortlist",
        callback_data=f"shortlist:toggle:{normalized_item_id}",
    )


def build_inline_reply_markup(action_buttons: tuple[TelegramActionButton, ...]) -> dict[str, list[list[dict[str, str]]]] | None:
    if not action_buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": button.text, "callback_data": button.callback_data}] for button in action_buttons
        ]
    }


def build_news_card(
    headline: str,
    summary_text: str | None,
    url: str,
    *,
    action_buttons: tuple[TelegramActionButton, ...] = (),
) -> TelegramCard | None:
    if not headline.strip() or not summary_text or not url.strip():
        return None
    cleaned_summary = _normalize_card_summary(headline, summary_text)
    if not cleaned_summary:
        return None
    text = "\n\n".join(
        [
            f"<b>{html.escape(headline)}</b>",
            html.escape(cleaned_summary),
            f'<a href="{html.escape(url, quote=True)}">Link</a>',
        ]
    )
    return TelegramCard(
        text=text,
        headline=headline,
        summary_text=cleaned_summary,
        url=url,
        action_buttons=action_buttons,
    )


@dataclass(frozen=True)
class TelegramDelivery:
    chat_id: str
    status: str
    telegram_message_id: str | None
    error_text: str | None
    payload_text: str


def build_replay_card(card: TelegramCard, replay_label: str) -> TelegramCard:
    replay_prefix = f"<i>{html.escape(replay_label)}</i>"
    return TelegramCard(
        text=f"{replay_prefix}\n\n{card.text}",
        headline=card.headline,
        summary_text=card.summary_text,
        url=card.url,
        action_buttons=card.action_buttons,
    )


class TelegramSender:
    def __init__(self, bot_token: str | None, chat_ids: tuple[str, ...]) -> None:
        self.bot_token = bot_token
        self.chat_ids = chat_ids

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_ids)

    def send_card(self, card: TelegramCard) -> list[TelegramDelivery]:
        if not self.is_configured:
            return [
                TelegramDelivery(
                    chat_id="",
                    status="skipped",
                    telegram_message_id=None,
                    error_text="telegram_not_configured",
                    payload_text=card.text,
                )
            ]

        deliveries: list[TelegramDelivery] = []
        for chat_id in self.chat_ids:
            endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": card.text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }
            reply_markup = build_inline_reply_markup(card.action_buttons)
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = json.loads(response.read().decode("utf-8"))
                deliveries.append(
                    TelegramDelivery(
                        chat_id=chat_id,
                        status="sent",
                        telegram_message_id=str(body.get("result", {}).get("message_id", uuid.uuid4().hex)),
                        error_text=None,
                        payload_text=card.text,
                    )
                )
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                deliveries.append(
                    TelegramDelivery(
                        chat_id=chat_id,
                        status="failed",
                        telegram_message_id=None,
                        error_text=str(exc),
                        payload_text=card.text,
                    )
                )
        return deliveries
