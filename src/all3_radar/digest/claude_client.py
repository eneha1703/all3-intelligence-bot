"""Minimal optional Claude client for weekly digest synthesis."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class ClaudeDigestUnavailableError(RuntimeError):
    """Raised when Claude digest synthesis is unavailable or invalid."""


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

    def generate_digest_section(self, prompt: str) -> str:
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
        if not text.startswith("## Claude Synthesis"):
            raise ClaudeDigestUnavailableError("Claude response was missing the required section header.")
        return text
