"""Minimal optional Claude client for weekly digest synthesis."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


class ClaudeDigestUnavailableError(RuntimeError):
    """Raised when Claude digest synthesis is unavailable or invalid."""


RAW_URL_RE = re.compile(r'(?<!href=")https?://[^\s<]+', re.IGNORECASE)
FENCED_JSON_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class ClaudeDigestClient:
    enabled: bool
    api_key: str | None
    model: str | None
    timeout_seconds: int
    max_tokens: int

    @property
    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.model)

    def _request_text(self, prompt: str) -> str:
        if not self.enabled:
            raise ClaudeDigestUnavailableError("CLAUDE_DIGEST_ENABLED is false.")
        if not self.api_key:
            raise ClaudeDigestUnavailableError("ANTHROPIC_API_KEY is not configured.")
        if not self.model:
            raise ClaudeDigestUnavailableError("CLAUDE_DIGEST_MODEL is not configured.")

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise ClaudeDigestUnavailableError(f"Claude request failed: {exc}") from exc

        try:
            content_blocks = body["content"]
            text = "".join(
                block.get("text", "")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
        except (KeyError, TypeError) as exc:
            raise ClaudeDigestUnavailableError("Claude response did not contain text content.") from exc

        if not text:
            raise ClaudeDigestUnavailableError("Claude response was empty.")
        return text

    def generate_digest_section(self, prompt: str) -> str:
        text = self._request_text(prompt)
        if not text.startswith("## Claude Synthesis"):
            raise ClaudeDigestUnavailableError("Claude response was missing the required section header.")
        return text

    def select_top_story_ids(self, prompt: str, *, allowed_ids: set[str], exact_count: int = 5) -> list[str]:
        text = self._request_text(prompt).strip()
        fence_match = FENCED_JSON_RE.match(text)
        if fence_match:
            text = fence_match.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeDigestUnavailableError("Claude selection response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ClaudeDigestUnavailableError("Claude selection response must be a JSON object.")
        selected_ids = payload.get("selected_ids")
        if not isinstance(selected_ids, list):
            raise ClaudeDigestUnavailableError("Claude selection response must include selected_ids.")
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in selected_ids:
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ClaudeDigestUnavailableError("Claude selection response contained an invalid selected id.")
            event_id = raw_id.strip()
            if event_id in seen:
                continue
            if event_id not in allowed_ids:
                raise ClaudeDigestUnavailableError("Claude selection response referenced an unknown candidate id.")
            seen.add(event_id)
            normalized_ids.append(event_id)
        if len(normalized_ids) != exact_count:
            raise ClaudeDigestUnavailableError(
                f"Claude selection response must contain exactly {exact_count} unique selected ids."
            )
        return normalized_ids

    def generate_telegram_digest(self, prompt: str, *, expected_title: str) -> str:
        text = self._request_text(prompt).strip()
        if not text.startswith(expected_title):
            raise ClaudeDigestUnavailableError("Claude digest response was missing the required title line.")
        if "<a href=" not in text:
            raise ClaudeDigestUnavailableError("Claude digest response was missing required HTML links.")
        if RAW_URL_RE.search(text):
            raise ClaudeDigestUnavailableError("Claude digest response exposed raw URLs in visible text.")
        return text
