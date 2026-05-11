"""Optional Claude final-card editor client for Bot 1 sendable candidates."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from all3_radar.domain.models import ClaudeFinalCardResult
from all3_radar.editorial_memory.prompt_context import build_radar_summary_memory_context

VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}
WHITESPACE_RE = re.compile(r"\s+")
FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'./-]*")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
BROKEN_DECIMAL_RE = re.compile(r"(?<=\d)\.\s+(?=\d)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9<])")
MAX_TITLE_LENGTH = 110
MAX_SUMMARY_LENGTH = 700
MAX_WHY_IT_MATTERS_LENGTH = 140
MIN_RICH_SUMMARY_WORDS = 30
TITLE_REPEAT_OVERLAP_RATIO = 0.8
RICH_DETAIL_TERMS = (
    "launch",
    "launched",
    "debut",
    "debuted",
    "opened",
    "headquarters",
    "product",
    "platform",
    "model",
    "system",
    "software",
    "cad",
    "photo",
    "video",
    "customer",
    "customers",
    "partner",
    "partners",
    "investor",
    "investors",
    "facility",
    "facilities",
    "factory",
    "factories",
    "deployment",
    "pilot",
    "production",
    "manufacturing",
    "timeline",
    "quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "u.s.",
    "el segundo",
    "data center",
    "data centres",
    "data centers",
)
FUNDING_BLURB_TERMS = ("raised", "raise", "closed", "secure", "secured", "series", "funding", "round")
HYPE_TERMS = (
    "revolutionary",
    "game-changing",
    "transformative",
    "pivotal",
    "cutting-edge",
    "poised to disrupt",
    "significant milestone",
)
REPO_ROOT = Path(__file__).resolve().parents[3]


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
    normalized = BROKEN_DECIMAL_RE.sub(".", normalized)
    return _truncate(normalized, MAX_SUMMARY_LENGTH)


def _sanitize_why_it_matters(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return _truncate(normalized, MAX_WHY_IT_MATTERS_LENGTH)


def _count_words(value: str | None) -> int:
    if not value:
        return 0
    return len(WORD_RE.findall(value))


def _contains_any_term(haystack: str, terms: tuple[str, ...]) -> bool:
    return any(term in haystack for term in terms)


def _token_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {token.lower() for token in WORD_RE.findall(value.lower()) if len(token) > 2}


def _mostly_repeats_headline(headline: str, summary: str) -> bool:
    headline_tokens = _token_set(headline)
    summary_tokens = _token_set(summary)
    if not headline_tokens or not summary_tokens:
        return False
    overlap = len(headline_tokens & summary_tokens) / max(1, len(headline_tokens))
    return overlap >= TITLE_REPEAT_OVERLAP_RATIO


def _source_has_richer_facts(text_preview: str | None, existing_summary: str | None) -> bool:
    source_text = (text_preview or existing_summary or "").lower()
    if not source_text:
        return False
    detail_score = 0
    if any(char.isdigit() for char in source_text):
        detail_score += 1
    if _contains_any_term(source_text, RICH_DETAIL_TERMS):
        detail_score += 1
    if source_text.count(".") >= 2 or len(source_text.split()) >= 25:
        detail_score += 1
    return detail_score >= 2


def _looks_like_thin_funding_blurb(summary: str) -> bool:
    lowered = summary.lower()
    return _contains_any_term(lowered, FUNDING_BLURB_TERMS) and _count_words(summary) < 22


def _summary_detail_score(summary: str) -> int:
    lowered = summary.lower()
    detail_score = 0
    if any(char.isdigit() for char in summary):
        detail_score += 1
    if _contains_any_term(lowered, RICH_DETAIL_TERMS):
        detail_score += 1
    if summary.count(".") >= 2 or len(summary.split()) >= 25:
        detail_score += 1
    return detail_score


def _has_trailing_fragment(summary: str) -> bool:
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(summary.strip()) if sentence.strip()]
    if len(sentences) < 2:
        lowered = summary.lower().strip()
        return lowered.endswith(
            (
                " once.",
                " while.",
                " with.",
                " after.",
                " before.",
                " because.",
                " although.",
                " when.",
                " where.",
                " which.",
                " including.",
                " such as.",
            )
        )
    last_sentence = sentences[-1]
    last_words = _count_words(last_sentence)
    if last_words <= 2:
        return True
    if last_words <= 4 and not any(char.isdigit() for char in last_sentence) and ":" not in last_sentence:
        return True
    return False


def _validate_summary_richness(
    *,
    input_title: str,
    summary: str,
    text_preview: str | None,
    existing_summary: str | None,
) -> None:
    if URL_RE.search(summary):
        raise ClaudeFinalCardUnavailableError("Claude final-card response summary must not contain raw URLs.")
    if _contains_any_term(summary.lower(), HYPE_TERMS):
        raise ClaudeFinalCardUnavailableError("Claude final-card response summary used hype language.")
    if _has_trailing_fragment(summary):
        raise ClaudeFinalCardUnavailableError("Claude final-card response summary ended in an incomplete fragment.")
    if _mostly_repeats_headline(input_title, summary):
        raise ClaudeFinalCardUnavailableError("Claude final-card response summary mostly repeated the headline.")
    if _source_has_richer_facts(text_preview, existing_summary):
        summary_words = _count_words(summary)
        if _looks_like_thin_funding_blurb(summary):
            raise ClaudeFinalCardUnavailableError(
                "Claude final-card response summary reduced a richer story to a funding blurb."
            )
        if summary_words < MIN_RICH_SUMMARY_WORDS and _summary_detail_score(summary) < 2:
            raise ClaudeFinalCardUnavailableError("Claude final-card response summary was too thin for the source detail.")


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
    memory_context = build_radar_summary_memory_context(REPO_ROOT)
    return (
        "You are reviewing one already-selected Bot 1 News Radar candidate. "
        "Do not select news from scratch. Do not broaden scope. Do not invent facts. "
        "You may only improve wording for a final Telegram card or reject the candidate when it is clearly duplicate, off-scope, generic, or insufficiently specific. "
        "Write in English. Write a Telegram-ready daily news card, not a weekly digest memo. "
        "Do not label stories with meta tags like PRESS RELEASE, BREAKING, or ALERT. "
        "Approve only when the story has a concrete All3-relevant operational signal such as physical AI, industrial robotics, "
        "factory automation directly tied to robotics, AI, or autonomous systems, construction automation, housing industrialization or productivity, "
        "timber adoption, scaling, economics, or policy, or strategically relevant robotics, automation, or platform funding or deployment. "
        "Treat real-world robot AI training infrastructure, robot data factories, operational fleet data collection, and physical-world training systems as valid operational signals when the story is clearly about robotics capability building in production-like environments. "
        "Reject generic automotive capex, gas-car production investment, EV demand or sales slowdown, tariff refund or trade policy stories, "
        "ordinary vehicle production investment, generic manufacturing investment without a robotics, AI, or automation signal, and generic executive, profile, or finance stories. "
        "Do not add a separate why-it-matters paragraph. Do not explain why the story matters to All3, the radar, or the industry. "
        "Do not use labels like Why it matters, Signal, Context, or Takeaway. "
        "Prefer one dense factual paragraph. Use two short paragraphs only if the article has several distinct factual points. "
        "Target about 45 to 90 words for the summary body, or about 35 to 60 words if the source is thin. Avoid one-line blurbs when the source has richer facts. "
        "Summarize the actual news by extracting the strongest two to four factual takeaways from the article. Prioritize key numbers, named companies, product or platform names, "
        "launch or deployment details, customers, partners, investors, geography, timelines, manufacturing or production scale, technical capabilities, business terms, and official statistics when present. "
        "If the article has a funding round plus a product launch, include both. If the title already states the main event, the body should add concrete details rather than repeat the title. "
        "Do not mostly repeat the headline. Do not reduce a rich article to a funding blurb when product, launch, customer, deployment, technical, location, timeline, or business details are present. "
        "Do not add broad industry analysis. Do not mention this article. Do not use hype language such as revolutionary, game-changing, transformative, pivotal, cutting-edge, or poised to disrupt. "
        "Avoid synthetic editorial phrasing, padded strategic commentary, and weekly-digest style essay writing. "
        "Stay close to the observed facts and write like a sharp daily news editor. "
        "Return only a single JSON object. Do not use markdown. Do not wrap the response in code fences. "
        "Do not include explanation outside JSON. "
        "Return JSON only with this exact schema: "
        '{"send_ok": boolean, "reject_reason": string|null, "title": string|null, "summary": string|null, '
        '"why_it_matters": string|null, "duplicate_risk": "low|medium|high"|null, "confidence": "low|medium|high"|null}. '
        "Keep title concrete and news-like, usually about 8 to 16 words. Keep summary factual, compact, and detail-rich. "
        "Set why_it_matters to null unless a brief factual note is truly necessary, and never use it for broad analysis.\n\n"
        f"{memory_context}\n\n"
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
        return self._validate_result(
            parsed,
            input_title=title,
            text_preview=text_preview,
            existing_summary=existing_summary,
        )

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
    def _validate_result(
        parsed: Any,
        *,
        input_title: str | None = None,
        text_preview: str | None = None,
        existing_summary: str | None = None,
    ) -> ClaudeFinalCardResult:
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
            _validate_summary_richness(
                input_title=input_title or title,
                summary=summary,
                text_preview=text_preview,
                existing_summary=existing_summary,
            )
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
