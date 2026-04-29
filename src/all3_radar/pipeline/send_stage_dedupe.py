"""Conservative late-stage duplicate suppression for final send candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem

FUNDING_VERB_RE = re.compile(r"\b(raises?|raised|lands?|landed|secures?|secured|bags?|bagged)\b", re.IGNORECASE)
ENTITY_RE = r"[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}"
PARTNERSHIP_ENTITY_RE = r"[A-Z][A-Za-z0-9&\-]*(?:\s+[A-Z][A-Za-z0-9&\-]*){0,3}"
PRODUCT_COMPANY_RE = re.compile(
    rf"^(?P<entity>{ENTITY_RE})\s+"
    r"(?P<verb>(?i:launches|launched|unveils|unveiled|introduces|introduced|releases|released|updates|updated|rolls out|rolled out|debuts|debuted))\b"
)
PRODUCT_VERB_PATTERN = (
    r"launches|launched|unveils|unveiled|introduces|introduced|releases|released|updates|updated|rolls out|rolled out|debuts|debuted"
)
TITLE_PRODUCT_RE = re.compile(
    rf"^(?P<entity>{ENTITY_RE})\s+(?P<verb>(?i:{PRODUCT_VERB_PATTERN}))\s+"
    r"(?P<product>[^.,;:]{0,120}?)\s+"
    r"(?=(?:to|for|with|across|on|into|targeting)\b|$)",
)
ITS_PRODUCT_RE = re.compile(
    r"\bits\s+(?:(?i:new|latest)\s+)?"
    r"(?P<product>[A-Z0-9][A-Za-z0-9&/\-]*(?:\s+[A-Z0-9][A-Za-z0-9&/\-]*){0,4})\s+"
    r"(?P<noun>(?i:platform|tool|software|system|assistant|controller|family|cobot(?:\s+family)?|robot))\b",
)
CALLED_PRODUCT_RE = re.compile(
    r"\b(?i:called)\s+(?:the\s+)?(?P<product>[A-Z0-9][A-Za-z0-9&/\-]*(?:\s+[A-Z0-9][A-Za-z0-9&/\-]*){0,4})\b",
)
PRODUCT_NOUN_RE = re.compile(
    r"\b(platform|tool|software|system|assistant|controller|family|cobot|robot)\b",
    re.IGNORECASE,
)
DIRECT_FUNDING_HEADLINE_RE = re.compile(
    rf"^(?P<entity>{ENTITY_RE})\s+"
    r"(?:has\s+)?(?:just\s+)?(?:raises?|raised|lands?|landed|secures?|secured|bags?|bagged)\b"
)
APPOSITIVE_FUNDING_RE = re.compile(
    rf"(?P<entity>{ENTITY_RE}),\s+"
    r"(?:an?|the)\s+[^.]{0,120}?\s+(?:has\s+)?(?:just\s+)?"
    r"(?:raises?|raised|lands?|landed|secures?|secured|bags?|bagged)\b"
)
STARTUP_ENTITY_RE = re.compile(
    rf"\b(?:startup|company|firm)\s+(?P<entity>{ENTITY_RE})\b"
)
PAIR_PARTNERSHIP_RE = re.compile(
    rf"(?P<left>{PARTNERSHIP_ENTITY_RE})\s+and\s+(?P<right>{PARTNERSHIP_ENTITY_RE})\s+"
    r"(?:(?i:is|are)\s+)?"
    r"(?:(?i:enter|enters|entered|expand|expands|expanded|expanding)\s+(?:their\s+|a\s+)?)?"
    r"(?:(?i:strategic|global|broader)\s+)?"
    r"(?P<event>(?i:partnership|collaboration|partner|partners|partnered|partnering))\b",
)
WITH_PARTNERSHIP_RE = re.compile(
    rf"(?P<left>{PARTNERSHIP_ENTITY_RE})\s+"
    r"(?P<event>(?i:partners with|partnered with|partnering with|collaborates with|collaborated with|collaborating with))\s+"
    rf"(?P<right>{PARTNERSHIP_ENTITY_RE})",
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
    group_reasons = {candidate.normalized_item_id: None for candidate in candidate_list}

    def find(item_id: str) -> str:
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def union(left_id: str, right_id: str, reason: str) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root != right_root:
            parent[right_root] = left_root
            group_reasons[left_root] = group_reasons[left_root] or group_reasons[right_root] or reason
        else:
            group_reasons[left_root] = group_reasons[left_root] or reason

    for index, left in enumerate(candidate_list):
        for right in candidate_list[index + 1 :]:
            if _is_same_funding_event(left, right):
                union(left.normalized_item_id, right.normalized_item_id, "duplicate_same_event_shortlist")
            elif _is_same_partnership_event(left, right):
                union(
                    left.normalized_item_id,
                    right.normalized_item_id,
                    "duplicate_same_partnership_event_shortlist",
                )
            elif _is_same_product_launch_event(left, right):
                union(
                    left.normalized_item_id,
                    right.normalized_item_id,
                    "duplicate_same_product_launch_event_shortlist",
                )

    grouped: dict[str, list[SendStageCandidate]] = {}
    for candidate in candidate_list:
        grouped.setdefault(find(candidate.normalized_item_id), []).append(candidate)

    suppressed: list[SuppressedDuplicate] = []
    for group in grouped.values():
        if len(group) < 2:
            continue
        representative = _choose_representative(group, score_tie_window=score_tie_window)
        reason = group_reasons.get(find(representative.normalized_item_id)) or "duplicate_same_event_shortlist"
        for candidate in group:
            if candidate.normalized_item_id == representative.normalized_item_id:
                continue
            suppressed.append(
                SuppressedDuplicate(
                    suppressed_item_id=candidate.normalized_item_id,
                    representative_item_id=representative.normalized_item_id,
                    reason=reason,
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
    if candidate.event_flags.get("partnership_event"):
        return _partnership_evidence_tuple(candidate)
    if candidate.event_flags.get("product_launch_event"):
        return _product_evidence_tuple(candidate)
    text = _candidate_text(candidate)
    return (
        int(_extract_primary_entity(text) is not None),
        int(_extract_amount(text) is not None),
        int(_extract_round(text) is not None),
        int(bool(_extract_investors(text))),
        int(_has_industrial_relevance(text)),
        _direct_event_framing_score(candidate.title),
    )


def _partnership_evidence_tuple(candidate: SendStageCandidate) -> tuple[int, int, int, int, int, int]:
    text = _candidate_text(candidate)
    return (
        int(_extract_partnership_entities(text) is not None),
        int(_has_industrial_relevance(text)),
        _direct_partnership_framing_score(candidate.title),
        int(bool(candidate.text_preview)),
        0,
        0,
    )


def _product_evidence_tuple(candidate: SendStageCandidate) -> tuple[int, int, int, int, int, int]:
    text = _candidate_text(candidate)
    product_key = _extract_product_launch_key(candidate)
    return (
        int(product_key is not None),
        int(product_key is not None and bool(product_key.product)),
        int(_has_industrial_relevance(text)),
        _direct_product_framing_score(candidate.title),
        int(bool(candidate.text_preview)),
        0,
    )


def _candidate_text(candidate: SendStageCandidate) -> str:
    if candidate.text_preview:
        return f"{candidate.title}. {candidate.text_preview}".strip()
    return candidate.title.strip()


def _is_same_partnership_event(left: SendStageCandidate, right: SendStageCandidate) -> bool:
    if not (left.event_flags.get("partnership_event") and right.event_flags.get("partnership_event")):
        return False

    left_date = left.published_ts.date() if left.published_ts else None
    right_date = right.published_ts.date() if right.published_ts else None
    if left_date is None or right_date is None:
        return False
    if abs((left_date - right_date).days) > 3:
        return False

    left_pair = _extract_partnership_entities(_candidate_text(left))
    right_pair = _extract_partnership_entities(_candidate_text(right))
    if left_pair is None or right_pair is None:
        return False
    return left_pair == right_pair


def _is_same_product_launch_event(left: SendStageCandidate, right: SendStageCandidate) -> bool:
    if not (left.event_flags.get("product_launch_event") and right.event_flags.get("product_launch_event")):
        return False

    left_date = left.published_ts.date() if left.published_ts else None
    right_date = right.published_ts.date() if right.published_ts else None
    if left_date is None or right_date is None:
        return False
    if abs((left_date - right_date).days) > 3:
        return False

    left_key = _extract_product_launch_key(left)
    right_key = _extract_product_launch_key(right)
    if left_key is None or right_key is None:
        return False
    return left_key == right_key


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


def _extract_partnership_entities(text: str) -> tuple[str, str] | None:
    pairs: set[tuple[str, str]] = set()
    for pattern in (PAIR_PARTNERSHIP_RE, WITH_PARTNERSHIP_RE):
        for match in pattern.finditer(text):
            left = _normalize_entity(match.group("left"))
            right = _normalize_entity(match.group("right"))
            if not left or not right or left == right:
                continue
            pairs.add(tuple(sorted((left, right))))
    if len(pairs) != 1:
        return None
    return next(iter(pairs))


@dataclass(frozen=True)
class ProductLaunchKey:
    company: str
    product: str


def _extract_product_launch_key(candidate: SendStageCandidate) -> ProductLaunchKey | None:
    title = candidate.title.strip()
    preview = (candidate.text_preview or "").strip()
    company = _extract_product_company(title)
    if company is None:
        return None

    preview_product = _extract_product_from_preview(preview)
    if preview_product is not None:
        return ProductLaunchKey(company=company, product=preview_product)

    title_product = _extract_product_from_title(title)
    if title_product is None:
        return None
    return ProductLaunchKey(company=company, product=title_product)


def _extract_product_company(title: str) -> str | None:
    match = PRODUCT_COMPANY_RE.search(title)
    if not match:
        return None
    return _normalize_entity(match.group("entity"))


def _extract_product_from_preview(preview: str) -> str | None:
    if not preview:
        return None

    products: set[str] = set()
    for match in ITS_PRODUCT_RE.finditer(preview):
        noun = match.group("noun").lower()
        candidate = _normalize_product_phrase(f"{match.group('product')} {noun}")
        if candidate:
            products.add(candidate)
    for match in CALLED_PRODUCT_RE.finditer(preview):
        candidate = _normalize_product_phrase(match.group("product"))
        if candidate:
            products.add(candidate)

    if len(products) != 1:
        return None
    return next(iter(products))


def _extract_product_from_title(title: str) -> str | None:
    match = TITLE_PRODUCT_RE.search(title)
    if not match:
        return None
    return _normalize_product_phrase(match.group("product"))


def _normalize_product_phrase(raw: str) -> str | None:
    lowered = re.sub(r"[\u2010-\u2015]", "-", raw).strip().lower()
    lowered = re.sub(r"[^a-z0-9&/\-\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip(" -/")
    if not lowered:
        return None
    if not PRODUCT_NOUN_RE.search(lowered):
        return None
    if lowered in {"platform", "tool", "software", "system", "assistant", "controller", "family", "robot", "cobot"}:
        return None
    if len(lowered.split()) == 1 and lowered in {"platforms", "tools", "systems", "robots", "cobots"}:
        return None
    return lowered


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


def _direct_partnership_framing_score(title: str) -> int:
    lowered = title.lower()
    score = 0
    if PAIR_PARTNERSHIP_RE.search(title) or WITH_PARTNERSHIP_RE.search(title):
        score += 2
    elif any(term in lowered for term in ("partnership", "partners with", "partnered with", "collaboration")):
        score += 1
    if any(phrase in lowered for phrase in CLICKBAIT_PHRASES):
        score -= 1
    return score


def _direct_product_framing_score(title: str) -> int:
    lowered = title.lower()
    score = 0
    if TITLE_PRODUCT_RE.search(title):
        score += 2
    elif any(term in lowered for term in ("launches", "launched", "updates", "updated", "introduces", "released")):
        score += 1
    if any(phrase in lowered for phrase in CLICKBAIT_PHRASES):
        score -= 1
    return score
