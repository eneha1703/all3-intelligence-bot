"""Telegram delivery for Bot 1."""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from all3_radar.domain.models import TelegramCard
from all3_radar.summarization.fallback_summary import sanitize_summary_text


def build_news_card(headline: str, summary_text: str | None, url: str) -> TelegramCard | None:
    if not headline.strip() or not summary_text or not url.strip():
        return None
    cleaned_summary = sanitize_summary_text(headline, summary_text)
    if not cleaned_summary:
        return None
    text = "\n".join(
        [
            f"<b>{html.escape(headline)}</b>",
            html.escape(cleaned_summary),
            f'<a href="{html.escape(url, quote=True)}">Link</a>',
        ]
    )
    return TelegramCard(text=text, headline=headline, summary_text=cleaned_summary, url=url)


@dataclass(frozen=True)
class TelegramDelivery:
    chat_id: str
    status: str
    telegram_message_id: str | None
    error_text: str | None
    payload_text: str


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
