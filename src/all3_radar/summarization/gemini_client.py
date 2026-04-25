"""Minimal Gemini client for optional Bot 1 summaries."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class GeminiUnavailableError(RuntimeError):
    """Raised when Gemini is not configured or fails."""


@dataclass(frozen=True)
class GeminiClient:
    api_key: str | None
    model: str

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
        if not self.api_key:
            raise GeminiUnavailableError("GEMINI_API_KEY is not configured.")

        prompt = (
            "Write a short factual news summary for a Telegram card. "
            "Use 2 short sentences when the source preview supports it; use 1 sentence only if that is still concrete and sufficient. "
            "Sentence 1 should say what happened. Sentence 2, when present, should add a concrete operational detail such as partner, deployment, facility, capacity, funding amount, product capability, customer, or location. "
            "Do not repeat the headline. Do not add hype, analysis, why-it-matters framing, vague filler, interview language, or commentary phrasing like 'discusses', 'explores', or 'future of'. "
            "Keep it factual, specific, and professional."
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
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise GeminiUnavailableError(f"Gemini request failed: {exc}") from exc

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiUnavailableError("Gemini response did not contain summary text.") from exc

        if borderline and text.upper().startswith("SKIP"):
            return "", "drop"
        return text, None
