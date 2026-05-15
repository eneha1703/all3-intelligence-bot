"""Claude duplicate review client for final pre-send repeat suppression."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from all3_radar.summarization.claude_editorial_review_client import (
    ClaudeEditorialReviewUnavailableError,
    _extract_json_object,
)

VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}


def build_claude_duplicate_review_prompt(
    *,
    candidate: dict[str, Any],
    recent_posts: list[dict[str, Any]],
) -> str:
    payload = {
        "candidate": candidate,
        "recent_group_posts": recent_posts,
    }
    return (
        "You are checking whether a Bot 1 News Radar candidate would be a duplicate of a story already posted "
        "in the Telegram group. This is not a scope review and not a rewrite task. "
        "Use a strict editorial duplicate standard focused on reader experience. "
        "If the candidate is the same news event, same funding round, same deployment announcement, "
        "same policy announcement, or the same operational milestone already posted under a different source framing, "
        "mark it as duplicate. "
        "Do not mark it as duplicate just because the same company appears again. "
        "If the newer story is a real follow-up with a new milestone, new amount, new partner, new site, "
        "new metric, or clearly new development, do not mark it as duplicate. "
        "For posts from the last 7 days, be stricter. For posts from 8 to 14 days ago, only mark duplicate when "
        "it is clearly the same event rather than a fresh development on the same company or topic. "
        "Return only a single JSON object with this exact schema: "
        '{"is_duplicate": boolean, "matched_index": integer|null, "confidence": "low|medium|high", "reason": string|null}. '
        "matched_index must be the zero-based index of the matching recent_group_posts item, or null if not duplicate. "
        "Do not use markdown. Do not include any text outside JSON.\n\n"
        f"Review JSON:\n{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


@dataclass(frozen=True)
class ClaudeDuplicateReviewResult:
    is_duplicate: bool
    matched_index: int | None
    confidence: str
    reason: str | None
    used_claude: bool


@dataclass(frozen=True)
class ClaudeDuplicateReviewClient:
    enabled: bool
    api_key: str | None
    model: str | None
    timeout_seconds: int
    max_tokens: int

    @property
    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.model)

    def review_candidate(
        self,
        *,
        candidate: dict[str, Any],
        recent_posts: list[dict[str, Any]],
    ) -> ClaudeDuplicateReviewResult:
        if not self.enabled:
            raise ClaudeEditorialReviewUnavailableError("unknown", "Claude duplicate review is disabled.")
        if not self.api_key:
            raise ClaudeEditorialReviewUnavailableError("unknown", "ANTHROPIC_API_KEY is not configured.")
        if not self.model:
            raise ClaudeEditorialReviewUnavailableError("unknown", "Claude duplicate review model is not configured.")

        prompt = build_claude_duplicate_review_prompt(candidate=candidate, recent_posts=recent_posts)
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
        except urllib.error.HTTPError as exc:
            raise ClaudeEditorialReviewUnavailableError(
                "api_http_error",
                "Claude duplicate review failed with HTTP error.",
                status_code=exc.code,
            ) from exc
        except TimeoutError as exc:
            raise ClaudeEditorialReviewUnavailableError(
                "api_timeout",
                "Claude duplicate review timed out.",
            ) from exc
        except urllib.error.URLError as exc:
            reason = "api_timeout" if isinstance(exc.reason, TimeoutError) else "api_network_error"
            raise ClaudeEditorialReviewUnavailableError(
                reason,
                "Claude duplicate review failed with network error.",
            ) from exc
        except json.JSONDecodeError as exc:
            raise ClaudeEditorialReviewUnavailableError(
                "api_json_decode_error",
                "Claude duplicate review API response was not valid JSON.",
            ) from exc

        content = self._extract_text(body)
        parsed = _extract_json_object(content)
        return self._validate_result(parsed)

    def _extract_text(self, body: dict[str, Any]) -> str:
        content = body.get("content")
        if not isinstance(content, list) or not content:
            raise ClaudeEditorialReviewUnavailableError(
                "response_empty",
                "Claude duplicate review response was empty.",
            )
        text_blocks: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    text_blocks.append(text.strip())
        if not text_blocks:
            raise ClaudeEditorialReviewUnavailableError(
                "response_missing_text",
                "Claude duplicate review response did not include text.",
            )
        return "\n".join(text_blocks)

    def _validate_result(self, payload: dict[str, Any]) -> ClaudeDuplicateReviewResult:
        if not isinstance(payload, dict):
            raise ClaudeEditorialReviewUnavailableError(
                "response_not_json",
                "Claude duplicate review response must be a JSON object.",
            )
        is_duplicate = payload.get("is_duplicate")
        confidence = payload.get("confidence")
        matched_index = payload.get("matched_index")
        reason = payload.get("reason")

        if not isinstance(is_duplicate, bool):
            raise ClaudeEditorialReviewUnavailableError(
                "response_missing_send_ok",
                "Claude duplicate review response must include boolean is_duplicate.",
            )
        if confidence not in VALID_CONFIDENCE_LEVELS:
            raise ClaudeEditorialReviewUnavailableError(
                "response_invalid_confidence",
                "Claude duplicate review response had invalid confidence.",
            )
        if matched_index is not None and not isinstance(matched_index, int):
            raise ClaudeEditorialReviewUnavailableError(
                "response_not_json",
                "Claude duplicate review matched_index must be an integer or null.",
            )
        if reason is not None and not isinstance(reason, str):
            raise ClaudeEditorialReviewUnavailableError(
                "response_not_json",
                "Claude duplicate review reason must be a string or null.",
            )
        return ClaudeDuplicateReviewResult(
            is_duplicate=is_duplicate,
            matched_index=matched_index,
            confidence=confidence,
            reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
            used_claude=True,
        )
