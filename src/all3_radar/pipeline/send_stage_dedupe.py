"""Conservative late-stage duplicate suppression for final send candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

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
    r"(?P<currency>[$€£])\s?(?P<value>\d+(?:\.\d+)?)\s?(?P<scale>m|mn|mm|million|b|bn|billion)?\b",
    re.IGNORECASE,
)
ROUND_RE = re.compile(r"\b(pre-seed|seed round|seed|series\s+[a-f])\b", re.IGNORECASE)
INVESTOR_RE = re.compile(
    r"\b(?:led by|from|backed by|with participation from)\s+"
    r"(?P<investor>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3})"
)

CLICKBAIT_PHRASES = (
    "the founders behind",
    "want to hire",
    "from sci-fi to reality",
    "here's why",
    "here is why",
    "how ",
    "why ",
)
INDUSTRIAL_RELEVANCE_TERMS = (
    "construction",
    "robotics",
    "robotic",
    "industrial",
    "manufacturing",
    "factory",
    "jobsite",
    "worksite",
    "automation",
)


@dataclass(frozen=True)
class SendStageCandidate:
    normalized_item_id: str
    canonical_url: str
    title: str
    text_preview: str | None
    published_ts: datetime | None
    score: int
    event_flags: Mapping[str, bool]


@dataclass(frozen=True)
class SuppressedDuplicate:
    suppressed_item_id: str
    representative_item_id: str
    reason: str


def candidate_from_item(item: StoredNormalizedItem, decision: RankedDecision) -> SendStageCandidate:
    event_flags = decision.signals.get("event_flags", {})
    if not isinstance(event_flags, Mapping):
        event_flags = {}
    return SendStageCandidate(
        normalized_item_id=item.normalized_item_id,
        canonical_url=item.canonical_url,
        title=item.title,
        text_preview=item.text_preview,
        published_ts=item.published_ts,
        score=decision.score,
        event_flags=event_flags,
    )


def suppress_same_event_funding_duplicates(
    candidates: Sequence[SendStageCandidate],
    score_tie_window: int = 5,
) -> list[SuppressedDuplicate]:
    candidate_list = list(candidates)
    if len(candidate_list) < 2:
        return []

    parent = {candidate.normalized_item_id: candidate.normalized_item_id for candidate in candidate_list}
    by_id = {candidate.normalized_item_id: candidate for candidate in candidate_list}

    def find(item_id: str) -> str:
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def union(left_id: str, right_id: str) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, left in enumerate(candidate_list):
        for right in candidate_list[index + 1 :]:
            if _is_same_funding_event(left, right):
                union(left.normalized_item_id, right.normalized_item_id)

    grouped: dict[str, list[SendStageCandidate]] = {}
    for candidate in candidate_list:
        grouped.setdefault(find(candidate.normalized_item_id), []).append(candidate)

    suppressed: list[SuppressedDuplicate] = []
    for group in grouped.values():
        if len(group) < 2:
            continue
        representative = _choose_representative(group, score_tie_window=score_tie_window)
        for candidate in group:
            if candidate.normalized_item_id == representative.normalized_item_id:
                continue
            suppressed.append(
                SuppressedDuplicate(
                    suppressed_item_id=candidate.normalized_item_id,
                    representative_item_id=representative.normalized_item_id,
                    reason="duplicate_same_event_shortlist",
                )
            )
    return sorted(suppressed, key=lambda item: item.suppressed_item_id)


def _is_same_funding_event(left: SendStageCandidate, right: SendStageCandidate) -> bool:
    if not (left.event_flags.get("funding_event") and right.event_flags.get("funding_event")):
        return False

    left_date = left.published_ts.date() if left.published_ts else None
    right_date = right.published_ts.date() if right.published_ts else None
    if left_date is None or right_date is None:
        return False
    if abs((left_date - right_date).days) > 3:
        return False

    left_text = _candidate_text(left)
    right_text = _candidate_text(right)

    left_entity = _extract_primary_entity(left_text)
    right_entity = _extract_primary_entity(right_text)
    if not left_entity or not right_entity or left_entity != right_entity:
        return False

    left_amount = _extract_amount(left_text)
    right_amount = _extract_amount(right_text)
    if left_amount and right_amount and left_amount == right_amount:
        return True

    left_round = _extract_round(left_text)
    right_round = _extract_round(right_text)
    if left_round and right_round and left_round == right_round:
        if left_amount and right_amount:
            return False
        left_investors = _extract_investors(left_text)
        right_investors = _extract_investors(right_text)
        if left_investors and right_investors and left_investors.intersection(right_investors):
            return True

    return False


def _choose_representative(group: Sequence[SendStageCandidate], score_tie_window: int) -> SendStageCandidate:
    representative = group[0]
    for candidate in group[1:]:
        if _compare_candidates(candidate, representative, score_tie_window=score_tie_window) > 0:
            representative = candidate
    return representative


def _compare_candidates(left: SendStageCandidate, right: SendStageCandidate, score_tie_window: int) -> int:
    score_gap = left.score - right.score
    if abs(score_gap) > score_tie_window:
        return 1 if score_gap > 0 else -1

    left_evidence = _evidence_tuple(left)
    right_evidence = _evidence_tuple(right)
    if left_evidence != right_evidence:
        return 1 if left_evidence > right_evidence else -1

    if score_gap:
        return 1 if score_gap > 0 else -1

    left_published = left.published_ts or datetime.min
    right_published = right.published_ts or datetime.min
    if left_published != right_published:
        return 1 if left_published > right_published else -1

    left_stable = left.canonical_url or left.normalized_item_id
    right_stable = right.canonical_url or right.normalized_item_id
    if left_stable == right_stable:
        return 0
    return 1 if left_stable < right_stable else -1


def _evidence_tuple(candidate: SendStageCandidate) -> tuple[int, int, int, int, int, int]:
    text = _candidate_text(candidate)
    return (
        int(_extract_primary_entity(text) is not None),
        int(_extract_amount(text) is not None),
        int(_extract_round(text) is not None),
        int(bool(_extract_investors(text))),
        int(_has_industrial_relevance(text)),
        _direct_event_framing_score(candidate.title),
    )


def _candidate_text(candidate: SendStageCandidate) -> str:
    return f"{candidate.title} {candidate.text_preview or ''}".strip()


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


def _extract_investors(text: str) -> set[str]:
    investors = set()
    for match in INVESTOR_RE.finditer(text):
        normalized = _normalize_entity(match.group("investor"))
        if normalized:
            investors.add(normalized)
    return investors


def _has_industrial_relevance(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in INDUSTRIAL_RELEVANCE_TERMS)


def _direct_event_framing_score(title: str) -> int:
    lowered = title.lower()
    score = 0
    if DIRECT_FUNDING_HEADLINE_RE.search(title):
        score += 2
    elif FUNDING_VERB_RE.search(title):
        score += 1
    if any(phrase in lowered for phrase in CLICKBAIT_PHRASES):
        score -= 1
    return score
