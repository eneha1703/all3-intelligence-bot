"""Send-stage editorial shaping for Bot 1 Telegram output."""

from __future__ import annotations

import re
from dataclasses import dataclass

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem

THOUGHT_LEADERSHIP_TERMS = (
    "future of",
    "future with",
    "from sci-fi to reality",
    "opinion",
    "commentary",
    "analysis",
    "thought leadership",
    "fireside chat",
    "roundtable",
    "keynote",
)
INTERVIEW_FORMAT_TERMS = (
    "with dr.",
    "podcast",
    "webinar",
    "summit",
    "expo",
    "interview",
    "q&a",
)
MILITARY_EXCLUDE_TERMS = (
    "military",
    "battlefield",
    "combat",
    "defense",
    "defence",
    "frontline",
    "weapon",
    "weapons",
    "missile",
    "munitions",
    "armed forces",
    "strike drone",
)
BUSINESS_PROFILE_EXCLUDE_TERMS = (
    "banker",
    "billionaire",
    "estate",
    "mansion",
    "luxury home",
    "luxury estate",
    "personal fortune",
    "net worth",
    "executive profile",
    "private residence",
    "villa",
)
PRODUCT_LAUNCH_TERMS = (
    "launches",
    "launch",
    "released",
    "release",
    "unveils",
    "update",
    "updates",
    "platform",
    "tool",
    "software",
    "capabilities",
)
OPERATIONAL_DETAIL_TERMS = (
    "deploy",
    "deployment",
    "factory",
    "factories",
    "manufacturing",
    "production",
    "production facility",
    "production facilities",
    "factory floor",
    "robot cells",
    "robot cell",
    "3d vision",
    "scara",
    "virtual twin",
    "virtual twins",
    "layout",
    "routes",
    "agv",
    "amr",
    "modular teaching spaces",
    "jobsite",
    "worksite",
)
CONSTRUCTION_EXECUTION_TERMS = (
    "modular",
    "prefab",
    "prefabrication",
    "off-site",
    "offsite",
    "assembly",
    "factory-built",
    "construction",
    "building",
    "component",
)
WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.lower()).strip()


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = _normalize_text(text)
    return any(_term_pattern(term).search(normalized) for term in terms)


@dataclass(frozen=True)
class EditorialDecision:
    allow_send: bool
    reason: str | None
    flags: dict[str, bool]


def evaluate_send_stage_editorial(item: StoredNormalizedItem, decision: RankedDecision) -> EditorialDecision:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    event_flags = decision.signals.get("event_flags", {})
    competitor_count = int(decision.signals.get("competitor_count", 0) or 0)
    military_excluded = _contains_any(haystack, MILITARY_EXCLUDE_TERMS)
    business_profile_excluded = _contains_any(haystack, BUSINESS_PROFILE_EXCLUDE_TERMS)

    thought_leadership_format = _contains_any(haystack, THOUGHT_LEADERSHIP_TERMS) or _contains_any(
        haystack, INTERVIEW_FORMAT_TERMS
    )
    product_launch = _contains_any(haystack, PRODUCT_LAUNCH_TERMS)
    operational_detail = _contains_any(haystack, OPERATIONAL_DETAIL_TERMS)
    construction_execution = _contains_any(haystack, CONSTRUCTION_EXECUTION_TERMS)

    hard_news_event = any(
        (
            event_flags.get("deployment_event", False),
            event_flags.get("funding_event", False),
            event_flags.get("partnership_event", False),
            event_flags.get("acquisition_event", False),
            event_flags.get("factory_opening_or_expansion", False),
            event_flags.get("permitting_or_code_signal", False),
            event_flags.get("quantified_scale_signal", False),
            event_flags.get("timber_strategic_signal", False),
        )
    )
    industrial_relevance = any(
        (
            event_flags.get("industrial_robotics_signal", False),
            event_flags.get("deployment_event", False),
            event_flags.get("factory_opening_or_expansion", False),
            event_flags.get("construction_innovation_signal", False),
        )
    )
    adjacent_logistics_only = bool(event_flags.get("adjacent_logistics_only", False))
    tangible_operational_signal = operational_detail or construction_execution or industrial_relevance
    product_or_platform_news = product_launch and tangible_operational_signal and (
        industrial_relevance or construction_execution or competitor_count > 0
    )
    telegram_worthy = (
        (hard_news_event and tangible_operational_signal and not adjacent_logistics_only)
        or product_or_platform_news
        or (construction_execution and event_flags.get("quantified_scale_signal", False))
    )

    flags = {
        "military_excluded": military_excluded,
        "business_profile_excluded": business_profile_excluded,
        "thought_leadership_format": thought_leadership_format,
        "product_launch": product_launch,
        "operational_detail": operational_detail,
        "construction_execution": construction_execution,
        "hard_news_event": hard_news_event,
        "industrial_relevance": industrial_relevance,
        "adjacent_logistics_only": adjacent_logistics_only,
        "tangible_operational_signal": tangible_operational_signal,
        "telegram_worthy": telegram_worthy,
    }

    if military_excluded:
        return EditorialDecision(
            allow_send=False,
            reason="editorial_military_or_combat_out_of_scope",
            flags=flags,
        )
    if business_profile_excluded and competitor_count == 0:
        return EditorialDecision(
            allow_send=False,
            reason="editorial_business_profile_out_of_scope",
            flags=flags,
        )
    if thought_leadership_format and not hard_news_event:
        return EditorialDecision(
            allow_send=False,
            reason="editorial_thought_leadership_without_operational_signal",
            flags=flags,
        )
    if thought_leadership_format and not tangible_operational_signal:
        return EditorialDecision(
            allow_send=False,
            reason="editorial_commentary_without_tangible_detail",
            flags=flags,
        )
    if adjacent_logistics_only and not (construction_execution or competitor_count > 0):
        return EditorialDecision(
            allow_send=False,
            reason="editorial_adjacent_logistics_without_all3_signal",
            flags=flags,
        )
    if not telegram_worthy:
        return EditorialDecision(
            allow_send=False,
            reason="editorial_not_telegram_worthy",
            flags=flags,
        )
    return EditorialDecision(allow_send=True, reason=None, flags=flags)
