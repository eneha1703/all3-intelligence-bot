"""Conservative semantic matching for cross-run funding sent-history checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem

FUNDING_VERB_RE = re.compile(r"\b(raises?|raised|lands?|landed|secures?|secured|bags?|bagged)\b", re.IGNORECASE)
DIRECT_FUNDING_HEADLINE_RE = re.compile(
    r"^(?P<entity>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3})\s+"
    r"(?:has\s+)?(?:just\s+)?(?:raises?|raised|lands?|landed|secures?|secured|bags?|bagged)\b"
)
APPOSITIVE_FUNDING_RE = re.compile(
    r"(?P<entity>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}),\s+"
    r"(?:an?|the)\s+[^.]{0,120}?\s+(?:has\s+)?(?:just\s+)?"
    r"(?:raises?|raised|lands?|landed|secures?|secured|bags?|bagged)\b"
)
STARTUP_ENTITY_RE = re.compile(
    r"\b(?:startup|company|firm)\s+(?P<entity>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3})\b"
)
AMOUNT_RE = re.compile(
    r"(?P<currency>[$в‚¬ВЈ])\s?(?P<value>\d+(?:\.\d+)?)\s?(?P<scale>m|mn|mm|million|b|bn|billion)?\b",
    re.IGNORECASE,
)
ROUND_RE = re.compile(r"\b(pre-seed|seed round|seed|series\s+[a-f])\b", re.IGNORECASE)


@dataclass(frozen=True)
class FundingSemanticKey:
    entity: str
    amount: tuple[str, str, str]
    round_marker: str | None
    published_date: date


def funding_key_from_candidate(item: StoredNormalizedItem, decision: RankedDecision) -> FundingSemanticKey | None:
    event_flags = decision.signals.get("event_flags", {})
    if not isinstance(event_flags, Mapping):
        event_flags = {}
    return funding_key_from_text(
        title=item.title,
        preview=item.text_preview,
        published_ts=item.published_ts,
        event_flags=event_flags,
    )


def funding_key_from_text(
    title: str,
    preview: str | None,
    published_ts: datetime | None,
    event_flags: Mapping[str, object],
) -> FundingSemanticKey | None:
    if not bool(event_flags.get("funding_event")):
        return None
    if published_ts is None:
        return None
    text = f"{title} {preview or ''}".strip()
    entity = _extract_primary_entity(text)
    amount = _extract_amount(text)
    if entity is None or amount is None:
        return None
    return FundingSemanticKey(
        entity=entity,
        amount=amount,
        round_marker=_extract_round(text),
        published_date=published_ts.date(),
    )


def same_funding_event(
    current: FundingSemanticKey,
    previous: FundingSemanticKey,
    max_day_delta: int = 3,
) -> bool:
    if current.entity != previous.entity:
        return False
    if current.amount != previous.amount:
        return False
    if current.round_marker != previous.round_marker:
        return False
    return abs((current.published_date - previous.published_date).days) <= max_day_delta


def _extract_primary_entity(text: str) -> str | None:
    for pattern in (DIRECT_FUNDING_HEADLINE_RE, APPOSITIVE_FUNDING_RE, STARTUP_ENTITY_RE):
        match = pattern.search(text)
        if match:
            normalized = _normalize_entity(match.group("entity"))
            if normalized:
                return normalized
    return None


def _normalize_entity(raw: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", raw).strip().lower()
    if not cleaned or cleaned in {"the", "a", "an", "startup", "company", "firm"}:
        return None
    return re.sub(r"\s+", " ", cleaned)


def _extract_amount(text: str) -> tuple[str, str, str] | None:
    matches = list(AMOUNT_RE.finditer(text))
    if not matches:
        return None
    funding_match = FUNDING_VERB_RE.search(text)
    selected = None
    if funding_match is not None:
        for match in matches:
            if match.start() > funding_match.start():
                selected = match
                break
    if selected is None:
        selected = matches[-1]
    currency = selected.group("currency")
    value = str(float(selected.group("value"))).rstrip("0").rstrip(".")
    scale = (selected.group("scale") or "").lower()
    if scale in {"mn", "mm", "million"}:
        scale = "m"
    if scale in {"bn", "billion"}:
        scale = "b"
    return currency, value, scale


def _extract_round(text: str) -> str | None:
    match = ROUND_RE.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1).lower())
