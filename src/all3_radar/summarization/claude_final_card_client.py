"""Optional Claude final-card editor client for Bot 1 sendable candidates."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from all3_radar.domain.models import ClaudeFinalCardResult
from all3_radar.summarization.fallback_summary import sanitize_summary_text

VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}
WHITESPACE_RE = re.compile(r"\s+")
FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
MAX_TITLE_LENGTH = 110
MAX_SUMMARY_LENGTH = 280
MAX_WHY_IT_MATTERS_LENGTH = 140


class ClaudeFinalCardUnavailableError(RuntimeError):
    """Raised when Claude final-card editing is unavailable or invalid."""


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


def _sanitize_why_it_matters(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return _truncate(normalized, MAX_WHY_IT_MATTERS_LENGTH)


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        raise ClaudeFinalCardUnavailableError("Claude final-card response was not valid JSON.")

    fenced_match = FENCED_JSON_RE.search(stripped)
    if fenced_match:
        return fenced_match.group(1).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    balanced = _extract_balanced_json_object(stripped)
    if balanced is None:
        raise ClaudeFinalCardUnavailableError("Claude final-card response was not valid JSON.")

    trailing = stripped[stripped.find(balanced) + len(balanced) :].strip()
    if "{" in trailing:
        raise ClaudeFinalCardUnavailableError("Claude final-card response was not valid JSON.")
    return balanced


def build_claude_final_card_prompt(
    *,
    title: str,
    source: str,
    url: str,
    text_preview: str | None,
    score: int,
    event_flags: dict[str, Any],
    signals: dict[str, Any],
    existing_summary: str | None,
) -> str:
    payload = {
        "title": title,
        "source": source,
        "url": url,
        "text_preview": text_preview,
        "score": score,
        "event_flags": event_flags,
        "signals": signals,
        "existing_summary": existing_summary,
    }
    return (
        "You are reviewing one already-selected Bot 1 News Radar candidate. "
        "Do not select news from scratch. Do not broaden scope. Do not invent facts. "
        "You may only improve wording for a final Telegram card or reject the candidate when it is clearly duplicate, off-scope, generic, or insufficiently specific. "
        "Approve only when the story has a concrete All3-relevant operational signal such as physical AI, industrial robotics, "
        "factory automation directly tied to robotics, AI, or autonomous systems, construction automation, housing industrialization or productivity, "
        "timber adoption, scaling, economics, or policy, or strategically relevant robotics, automation, or platform funding or deployment. "
        "Reject generic automotive capex, gas-car production investment, EV demand or sales slowdown, tariff refund or trade policy stories, "
        "ordinary vehicle production investment, generic manufacturing investment without a robotics, AI, or automation signal, and generic executive, profile, or finance stories. "
        "Return only a single JSON object. Do not use markdown. Do not wrap the response in code fences. "
        "Do not include explanation outside JSON. "
        "Return JSON only with this exact schema: "
        '{"send_ok": boolean, "reject_reason": string|null, "title": string|null, "summary": string|null, '
        '"why_it_matters": string|null, "duplicate_risk": "low|medium|high"|null, "confidence": "low|medium|high"|null}. '
        "Keep title short and factual. Keep summary short and factual. "
        "why_it_matters must be one short factual sentence, not hype.\n\n"
        f"Candidate JSON:\n{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


@dataclass(frozen=True)
class ClaudeFinalCardClient:
    enabled: bool
    api_key: str | None
    model: str | None
    timeout_seconds: int
    max_tokens: int

    @property
    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.model)

    def generate_final_card(
        self,
        *,
        title: str,
        source: str,
        url: str,
        text_preview: str | None,
        score: int,
        event_flags: dict[str, Any],
        signals: dict[str, Any],
        existing_summary: str | None,
    ) -> ClaudeFinalCardResult:
        if not self.enabled:
            raise ClaudeFinalCardUnavailableError("CLAUDE_FINAL_CARD_ENABLED is false.")
        if not self.api_key:
            raise ClaudeFinalCardUnavailableError("ANTHROPIC_API_KEY is not configured.")
        if not self.model:
            raise ClaudeFinalCardUnavailableError("CLAUDE_FINAL_CARD_MODEL is not configured.")

        prompt = build_claude_final_card_prompt(
            title=title,
            source=source,
            url=url,
            text_preview=text_preview,
            score=score,
            event_flags=event_flags,
            signals=signals,
            existing_summary=existing_summary,
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
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise ClaudeFinalCardUnavailableError(f"Claude request failed: {exc}") from exc

        content = self._extract_text(body)
        try:
            parsed = json.loads(_extract_json_object(content))
        except json.JSONDecodeError as exc:
            raise ClaudeFinalCardUnavailableError("Claude final-card response was not valid JSON.") from exc
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
            raise ClaudeFinalCardUnavailableError("Claude response did not contain text content.") from exc
        if not text:
            raise ClaudeFinalCardUnavailableError("Claude response was empty.")
        return text

    @staticmethod
    def _validate_result(parsed: Any) -> ClaudeFinalCardResult:
        if not isinstance(parsed, dict):
            raise ClaudeFinalCardUnavailableError("Claude final-card response must be a JSON object.")
        if "send_ok" not in parsed or not isinstance(parsed["send_ok"], bool):
            raise ClaudeFinalCardUnavailableError("Claude final-card response must include boolean send_ok.")

        send_ok = parsed["send_ok"]
        reject_reason = _normalize_text(parsed.get("reject_reason"))
        duplicate_risk = _normalize_text(parsed.get("duplicate_risk"))
        confidence = _normalize_text(parsed.get("confidence"))
        if duplicate_risk is not None and duplicate_risk not in VALID_RISK_LEVELS:
            raise ClaudeFinalCardUnavailableError("Claude final-card response had invalid duplicate_risk.")
        if confidence is not None and confidence not in VALID_CONFIDENCE_LEVELS:
            raise ClaudeFinalCardUnavailableError("Claude final-card response had invalid confidence.")

        title = _sanitize_title(parsed.get("title"))
        summary = _sanitize_summary(title or "", parsed.get("summary")) if title else None
        why_it_matters = _sanitize_why_it_matters(parsed.get("why_it_matters"))

        if send_ok:
            if title is None:
                raise ClaudeFinalCardUnavailableError("Claude final-card response was missing a usable title.")
            summary = _sanitize_summary(title, parsed.get("summary"))
            if summary is None:
                raise ClaudeFinalCardUnavailableError("Claude final-card response was missing a usable summary.")
        else:
            if reject_reason is None:
                raise ClaudeFinalCardUnavailableError(
                    "Claude final-card rejection response must include reject_reason."
                )
            title = None
            summary = None
            why_it_matters = None

        return ClaudeFinalCardResult(
            send_ok=send_ok,
            reject_reason=reject_reason,
            title=title,
            summary=summary,
            why_it_matters=why_it_matters,
            duplicate_risk=duplicate_risk,
            confidence=confidence,
            used_claude=True,
        )
