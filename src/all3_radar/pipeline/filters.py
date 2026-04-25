"""Rule-based filtering for Bot 1."""

from __future__ import annotations

import re
from pathlib import Path

from all3_radar.config.loader import load_yaml
from all3_radar.domain.models import RankedDecision, StoredNormalizedItem

CONSUMER_ROBOT_TERMS = {
    "home robot",
    "domestic robot",
    "home assistant",
    "robot vacuum",
    "companion robot",
    "entertainment robot",
    "toy robot",
    "consumer robot",
}
INDUSTRIAL_CONTEXT_TERMS = {
    "construction",
    "industrial",
    "warehouse",
    "manufacturing",
    "logistics",
    "jobsite",
    "factory",
    "prefab",
    "modular",
}
TOPIC_TERMS = {
    "robot",
    "robotics",
    "automation",
    "autonomy",
    "prefab",
    "prefabrication",
    "modular",
    "offsite",
    "off-site",
    "osm",
    "construction",
    "contech",
    "timber",
    "mass timber",
    "factory",
    "housing",
    "permitting",
    "code",
    "policy",
}
WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.lower()).strip()


def load_topic_rules(path: Path) -> dict:
    return load_yaml(path)


def has_any_term(text: str, terms: set[str]) -> bool:
    normalized = _normalize_text(text)
    return any(term in normalized for term in terms)


def is_obvious_off_scope(item: StoredNormalizedItem) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    if has_any_term(haystack, CONSUMER_ROBOT_TERMS) and not has_any_term(haystack, INDUSTRIAL_CONTEXT_TERMS):
        return True
    return False


def has_topic_relevance(item: StoredNormalizedItem, competitor_count: int, event_flags: dict[str, bool]) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return competitor_count > 0 or has_any_term(haystack, TOPIC_TERMS) or any(event_flags.values())


def compute_relevance_status(
    item: StoredNormalizedItem,
    competitor_count: int,
    freshness_is_fresh: bool,
    event_flags: dict[str, bool],
) -> tuple[str, str | None]:
    if not freshness_is_fresh:
        return "drop", "freshness_failed"
    if is_obvious_off_scope(item):
        return "drop", "obvious_off_scope"
    if not has_topic_relevance(item, competitor_count, event_flags):
        return "drop", "no_clear_topic_signal"
    return "keep", None
