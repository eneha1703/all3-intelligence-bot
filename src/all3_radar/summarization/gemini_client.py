"""Minimal Gemini client for optional Bot 1 summaries."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


class GeminiUnavailableError(RuntimeError):
    """Raised when Gemini is not configured or fails."""


@dataclass
class GeminiClient:
    api_key: str | None
    model: str
    _disabled_reason: str | None = field(default=None, init=False, repr=False)

    @property
    def is_available(self) -> bool:
        return bool(self.api_key) and self._disabled_reason is None

    def _generate_text(self, prompt: str) -> str:
        if self._disabled_reason is not None:
            raise GeminiUnavailableError(self._disabled_reason)
        if not self.api_key:
            raise GeminiUnavailableError("GEMINI_API_KEY is not configured.")

        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(self.model)}:"
            f"generateContent?key={urllib.parse.quote(self.api_key)}"
        )
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                self._disabled_reason = "Gemini disabled for run after HTTP 429 rate limit."
            raise GeminiUnavailableError(f"Gemini request failed: {exc}") from exc
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise GeminiUnavailableError(f"Gemini request failed: {exc}") from exc

        try:
            return body["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiUnavailableError("Gemini response did not contain summary text.") from exc

    def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
        prompt = (
            "Write a short factual Telegram news summary in 2 or 3 short sentences when the source preview supports it. "
            "Use 1 sentence only if no second concrete fact is available. "
            "Sentence 1 must say what happened. "
            "Sentence 2 must give the most important concrete fact such as funding amount, partner, deployment, facility, capacity, product capability, customer, location, or scale. "
            "Sentence 3 is optional and only allowed if it adds another specific factual detail. "
            "Do not repeat the headline. Do not write why-it-matters framing, strategic interpretation, commentary, speculation, hype, or filler. "
            "Do not use wording like 'discusses', 'explores', 'future of', or 'shares insights'. "
            "Keep each sentence short, clear, and strictly factual."
        )
        if borderline:
            prompt += (
                " If the item is clearly off-scope for construction, industrial automation, prefab/modular,"
                " timber strategy, or built-environment operations, respond with 'SKIP'."
            )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"{prompt}\n\nHeadline: {title}\n"
                                f"Preview: {preview or '(none)'}"
                            )
                        }
                    ]
                }
            ]
        }
        text = self._generate_text(payload["contents"][0]["parts"][0]["text"])

        if borderline and text.upper().startswith("SKIP"):
            return "", "drop"
        return text, None

    def rewrite_delivery_card(
        self,
        *,
        title: str,
        summary: str,
        source_language: str,
        target_language: str = "English",
    ) -> tuple[str, str]:
        prompt = (
            f"Rewrite this Telegram-ready news card into natural factual {target_language}. "
            "Translate when needed. Keep it concise and human. "
            "Do not add analysis, hype, or why-it-matters commentary. "
            "Keep the headline concrete and news-like. Keep the summary to one short factual paragraph. "
            "Return JSON only with this exact schema: "
            '{"title": string, "summary": string}. '
            f"Source language: {source_language}.\n\n"
            f"Title: {title}\n"
            f"Summary: {summary}"
        )
        text = self._generate_text(prompt)
        try:
            payload = json.loads(text)
            rewritten_title = str(payload["title"]).strip()
            rewritten_summary = str(payload["summary"]).strip()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise GeminiUnavailableError("Gemini translation response was not valid JSON.") from exc
        if not rewritten_title or not rewritten_summary:
            raise GeminiUnavailableError("Gemini translation response was missing card fields.")
        return rewritten_title, rewritten_summary
