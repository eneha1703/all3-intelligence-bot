"""Claude editorial review client for borderline Bot 1 News Radar candidates."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from all3_radar.summarization.fallback_summary import sanitize_summary_text

VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}
WHITESPACE_RE = re.compile(r"\s+")
FENCED_JSON_RE = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
MAX_TITLE_LENGTH = 110
MAX_SUMMARY_LENGTH = 280


class ClaudeEditorialReviewUnavailableError(RuntimeError):
    """Raised when Claude editorial review is unavailable or invalid."""

    def __init__(
        self,
        reason: str,
        message: str | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(message or reason)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = WHITESPACE_RE.sub(" ", value).strip()
    return normalized or None


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    truncated = value[: max_length + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not truncated:
        truncated = value[:max_length].rstrip(" ,;:-")
    return truncated


def _sanitize_title(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return _truncate(normalized, MAX_TITLE_LENGTH)


def _sanitize_summary(headline: str, value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    sanitized = sanitize_summary_text(headline, normalized)
    if not sanitized:
        return None
    return _truncate(sanitized, MAX_SUMMARY_LENGTH)


def _parse_json_object(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            character = text[index]
            if in_string:
                if escape:
                    escape = False
                elif character == "\\":
                    escape = True
                elif character == '"':
                    in_string = False
                continue

            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


def _extract_json_object(text: str) -> dict[str, Any]:
    parsed = _parse_json_object(text)
    if parsed is not None:
        return parsed

    fenced_match = FENCED_JSON_RE.match(text)
    if fenced_match is not None:
        parsed = _parse_json_object(fenced_match.group("body").strip())
        if parsed is not None:
            return parsed

    candidate = _extract_balanced_json_object(text)
    if candidate is None:
        raise ClaudeEditorialReviewUnavailableError(
            "response_not_json",
            "Claude editorial review response was not valid JSON.",
        )

    trailing = text[text.index(candidate) + len(candidate) :]
    if "{" in trailing:
        raise ClaudeEditorialReviewUnavailableError(
            "response_not_json",
            "Claude editorial review response contained multiple JSON objects.",
        )

    parsed = _parse_json_object(candidate)
    if parsed is None:
        raise ClaudeEditorialReviewUnavailableError(
            "response_not_json",
            "Claude editorial review response was not valid JSON.",
        )
    return parsed


def build_claude_editorial_review_prompt(
    *,
    title: str,
    url: str,
    source: str,
    summary: str | None,
    score: int,
    ranking_signals: dict[str, Any],
    freshness: str | None,
    relevance: str | None,
) -> str:
    payload = {
        "title": title,
        "url": url,
        "source": source,
        "summary": summary,
        "score": score,
        "ranking_signals": ranking_signals,
        "freshness": freshness,
        "relevance": relevance,
    }
    return (
        "You are reviewing one already-shortlisted or borderline Bot 1 News Radar candidate. "
        "Do not select news from scratch. Do not broaden scope. Do not invent facts. "
        "Approve only concrete All3-relevant operational signals such as physical AI, industrial robotics, "
        "factory automation tied to robotics, AI, or autonomous systems, construction automation, "
        "housing industrialization or productivity, timber adoption, scaling, economics, or policy, "
        "or strategically relevant robotics, automation, platform funding, deployment, or physical infrastructure automation. "
        "Physical infrastructure automation includes robotics or data-center construction only when robotics or automation is central. "
        "Reject consumer AI, restaurant or menu personalization AI, generic automotive capex, gas-car or EV-demand stories, "
        "tariff or trade-policy stories, generic manufacturing without robotics, AI, or automation, "
        "and generic finance, profile, or executive stories. "
        "Return only a single JSON object with this exact schema. Do not use markdown. "
        "Do not wrap the response in code fences. Do not include explanation outside JSON. "
        "Use this exact schema: "
        '{"send_ok": boolean, "reject_reason": string|null, "edited_title": string|null, '
        '"edited_summary": string|null, "confidence": "low|medium|high"}. '
        "Use high confidence only when the candidate is clearly promotable or clearly rejectable. "
        "Use low or medium confidence when the deterministic pipeline should keep control.\n\n"
        f"Candidate JSON:\n{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


@dataclass(frozen=True)
class ClaudeEditorialReviewResult:
    send_ok: bool
    reject_reason: str | None
    edited_title: str | None
    edited_summary: str | None
    confidence: str
    used_claude: bool

    @property
    def is_high_confidence_promotion(self) -> bool:
        return (
            self.send_ok
            and self.confidence == "high"
            and self.edited_title is not None
            and self.edited_summary is not None
        )

    @property
    def is_high_confidence_rejection(self) -> bool:
        return (
            not self.send_ok
            and self.confidence == "high"
            and self.reject_reason is not None
        )


@dataclass(frozen=True)
class ClaudeEditorialReviewClient:
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
        title: str,
        url: str,
        source: str,
        summary: str | None,
        score: int,
        ranking_signals: dict[str, Any],
        freshness: str | None,
        relevance: str | None,
    ) -> ClaudeEditorialReviewResult:
        if not self.enabled:
            raise ClaudeEditorialReviewUnavailableError("unknown", "CLAUDE_EDITORIAL_ENABLED is false.")
        if not self.api_key:
            raise ClaudeEditorialReviewUnavailableError("unknown", "ANTHROPIC_API_KEY is not configured.")
        if not self.model:
            raise ClaudeEditorialReviewUnavailableError("unknown", "CLAUDE_EDITORIAL_MODEL is not configured.")

        prompt = build_claude_editorial_review_prompt(
            title=title,
            url=url,
            source=source,
            summary=summary,
            score=score,
            ranking_signals=ranking_signals,
            freshness=freshness,
            relevance=relevance,
        )
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
                "Claude request failed with HTTP error.",
                status_code=exc.code,
            ) from exc
        except TimeoutError as exc:
            raise ClaudeEditorialReviewUnavailableError(
                "api_timeout",
                "Claude request timed out.",
            ) from exc
        except urllib.error.URLError as exc:
            reason = "api_timeout" if isinstance(exc.reason, TimeoutError) else "api_network_error"
            raise ClaudeEditorialReviewUnavailableError(
                reason,
                "Claude request failed with network error.",
            ) from exc
        except json.JSONDecodeError as exc:
            raise ClaudeEditorialReviewUnavailableError(
                "api_json_decode_error",
                "Claude API response body was not valid JSON.",
            ) from exc

        content = self._extract_text(body)
        parsed = _extract_json_object(content)
        return self._validate_result(parsed)

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        try:
            content_blocks = body["content"]
            text = "".join(
                block.get("text", "")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
        except (KeyError, TypeError) as exc:
            raise ClaudeEditorialReviewUnavailableError(
                "response_missing_text",
                "Claude response did not contain text content.",
            ) from exc
        if not text:
            raise ClaudeEditorialReviewUnavailableError("response_empty", "Claude response was empty.")
        return text

    @staticmethod
    def _validate_result(parsed: Any) -> ClaudeEditorialReviewResult:
        if not isinstance(parsed, dict):
            raise ClaudeEditorialReviewUnavailableError(
                "response_not_json",
                "Claude editorial review response must be a JSON object.",
            )
        if "send_ok" not in parsed or not isinstance(parsed["send_ok"], bool):
            raise ClaudeEditorialReviewUnavailableError(
                "response_missing_send_ok",
                "Claude editorial review response must include boolean send_ok.",
            )

        send_ok = parsed["send_ok"]
        reject_reason = _normalize_text(parsed.get("reject_reason"))
        confidence = _normalize_text(parsed.get("confidence"))
        if confidence is None or confidence not in VALID_CONFIDENCE_LEVELS:
            raise ClaudeEditorialReviewUnavailableError(
                "response_invalid_confidence",
                "Claude editorial review response had invalid confidence.",
            )

        edited_title = _sanitize_title(parsed.get("edited_title"))
        edited_summary = _sanitize_summary(edited_title or "", parsed.get("edited_summary")) if edited_title else None

        if send_ok:
            if confidence == "high":
                if edited_title is None:
                    raise ClaudeEditorialReviewUnavailableError(
                        "response_invalid_promotion",
                        "Claude editorial review high-confidence promotion was missing a usable title.",
                    )
                edited_summary = _sanitize_summary(edited_title, parsed.get("edited_summary"))
                if edited_summary is None:
                    raise ClaudeEditorialReviewUnavailableError(
                        "response_invalid_promotion",
                        "Claude editorial review high-confidence promotion was missing a usable summary.",
                    )
            reject_reason = None
        else:
            edited_title = None
            edited_summary = None
            if confidence == "high" and reject_reason is None:
                raise ClaudeEditorialReviewUnavailableError(
                    "response_invalid_rejection",
                    "Claude editorial review high-confidence rejection must include reject_reason.",
                )

        return ClaudeEditorialReviewResult(
            send_ok=send_ok,
            reject_reason=reject_reason,
            edited_title=edited_title,
            edited_summary=edited_summary,
            confidence=confidence,
            used_claude=True,
        )
