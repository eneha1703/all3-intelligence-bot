"""Rule-based filtering for Bot 1."""

from __future__ import annotations

import re
from pathlib import Path

from all3_radar.config.loader import load_yaml
from all3_radar.domain.models import StoredNormalizedItem

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
MILITARY_ROBOTICS_TERMS = {
    "military robot",
    "military robotics",
    "battlefield robot",
    "battlefield robots",
    "battlefield robotics",
    "combat robot",
    "combat robots",
    "combat robotics",
    "combat drone",
    "combat drones",
    "defense robot",
    "defence robot",
    "defense robotics",
    "defence robotics",
    "war robot",
    "warfare robot",
    "battlefield",
    "combat",
    "defense",
    "defence",
    "frontline",
    "weapon system",
    "weapons system",
    "armed forces",
    "military drone",
    "strike drone",
    "lethal",
    "munitions",
    "missile",
}
GENERAL_BUSINESS_PROFILE_TERMS = {
    "banker",
    "billionaire",
    "estate",
    "mansion",
    "luxury home",
    "luxury estate",
    "personal fortune",
    "net worth",
    "executive profile",
    "wealth",
    "private residence",
    "villa",
}
MEDICAL_CONTEXT_TERMS = {
    "medical",
    "clinical",
    "diagnostic",
    "diagnostics",
    "healthcare",
    "hospital",
    "hospitals",
    "patient",
    "patients",
    "therapy",
    "therapeutic",
    "surgical",
    "surgeon",
    "surgeons",
    "physician",
    "physicians",
    "dermatology",
    "dermatologist",
    "dermatologists",
    "medtech",
    "skin cancer",
}
INDUSTRIAL_CONTEXT_TERMS = {
    "construction",
    "industrial",
    "manufacturing",
    "jobsite",
    "worksite",
    "factory",
    "prefab",
    "modular",
    "assembly",
    "production",
    "timber",
    "permitting",
    "code",
}
TOPIC_TERMS = {
    "robot",
    "robots",
    "robotics",
    "humanoid",
    "automation",
    "automated",
    "autonomy",
    "autonomous",
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
    "permitting",
    "code",
    "policy",
}
BROAD_FEED_SCOPE_TERMS = {
    "jobsite",
    "worksite",
    "prefab",
    "prefabrication",
    "modular",
    "off-site",
    "offsite",
    "industrialized",
    "industrialized construction",
    "construction robotics",
    "jobsite robotics",
    "industrial robot",
    "industrial robotics",
    "industrial automation",
    "construction automation",
    "construction equipment",
    "heavy equipment",
    "mass timber",
    "clt",
    "glulam",
    "permitting",
    "approval",
    "building code",
    "housing delivery",
    "modular housing",
    "factory-built housing",
}
HIGH_INTENT_BROAD_FEED_TERMS = {
    "jobsite",
    "worksite",
    "prefab",
    "prefabrication",
    "modular",
    "off-site",
    "offsite",
    "industrialized construction",
    "construction robotics",
    "jobsite robotics",
    "industrial robot",
    "industrial robotics",
    "industrial automation",
    "construction automation",
    "construction equipment",
    "heavy equipment",
    "mass timber",
    "clt",
    "glulam",
    "permitting",
    "building code",
    "housing delivery",
    "modular housing",
    "factory-built housing",
    "physical ai",
    "virtual twin",
    "virtual twins",
    "robot cell",
    "robot cells",
    "scara",
    "3d vision",
    "machine vision",
    "production facility",
    "production facilities",
    "factory floor",
    "factories",
}
WAREHOUSE_LOGISTICS_TERMS = {
    "warehouse",
    "warehousing",
    "logistics",
    "intralogistics",
    "material handling",
}
ROBOTICS_TERMS = {
    "robot",
    "robots",
    "robotics",
    "humanoid",
    "autonomy",
    "autonomous",
}
AUTOMATION_TERMS = {
    "automation",
    "automated",
}
STRATEGIC_WORK_ENV_TERMS = {
    "industrial",
    "manufacturing",
    "factory",
    "factories",
    "jobsite",
    "worksite",
    "production",
    "assembly",
}
INDUSTRIAL_ROBOTICS_CONTEXT_TERMS = {
    "physical ai",
    "virtual twin",
    "virtual twins",
    "robot cell",
    "robot cells",
    "scara",
    "3d vision",
    "machine vision",
    "robot programming",
    "programming platform",
    "production facility",
    "production facilities",
    "factory floor",
    "factories",
}
BUILT_ENVIRONMENT_TERMS = {
    "jobsite",
    "worksite",
    "prefab",
    "prefabrication",
    "modular",
    "offsite",
    "off-site",
    "industrialized construction",
    "housing delivery",
    "factory-built",
    "mass timber",
    "timber",
    "clt",
    "glulam",
    "permitting",
    "building code",
    "code approval",
}
DESTATIS_CONSTRUCTION_STATISTICS_TERMS = {
    "bauhauptgewerbe",
    "baugenehmigungen",
    "auftragseingang",
    "construction orders",
    "building permits",
    "housing approvals",
    "wohnungen",
}
STATISTICAL_SIGNAL_TERMS = {
    "%",
    "increase",
    "decrease",
    "higher",
    "lower",
    "month",
    "year",
    "vomormonat",
    "vorjahresmonat",
    "gestiegen",
    "gesunken",
}
WOOD_CENTRAL_TIMBER_POLICY_TERMS = {
    "cap",
    "code",
    "approval",
    "approvals",
    "approval pathway",
    "permitting",
    "insurance",
    "insurers",
    "standard",
    "standards",
    "regulation",
    "regulatory",
    "policy",
    "height",
    "fire",
}
WOOD_CENTRAL_TIMBER_ECONOMICS_TERMS = {
    "premium",
    "premiums",
    "cost",
    "costs",
    "price",
    "prices",
    "pricing",
    "economics",
    "economically",
}
WOOD_CENTRAL_TIMBER_QUANTIFIED_TERMS = {
    "%",
    "times higher",
    "times lower",
    "six to ten times",
    "higher than",
    "lower than",
}
WOOD_CENTRAL_TIMBER_COMMERCIAL_BARRIER_TERMS = {
    "commercial viability",
    "viability",
    "adoption barrier",
    "adoption barriers",
    "competitive",
    "competitiveness",
    "affordability",
    "commercial",
    "scaling",
    "scale-up",
    "cost comparison",
    "times higher",
    "times lower",
    "six to ten times",
    "higher than",
    "lower than",
}
WHITESPACE_RE = re.compile(r"\s+")


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.lower()).strip()


def load_topic_rules(path: Path) -> dict:
    return load_yaml(path)


def has_any_term(text: str, terms: set[str]) -> bool:
    normalized = _normalize_text(text)
    return any(_term_pattern(term).search(normalized) for term in terms)


def is_obvious_off_scope(item: StoredNormalizedItem) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    if has_any_term(haystack, MILITARY_ROBOTICS_TERMS):
        return True
    if (
        has_any_term(haystack, MEDICAL_CONTEXT_TERMS)
        and has_any_term(haystack, ROBOTICS_TERMS | AUTOMATION_TERMS)
        and not has_any_term(haystack, INDUSTRIAL_CONTEXT_TERMS | BUILT_ENVIRONMENT_TERMS)
    ):
        return True
    if has_any_term(haystack, CONSUMER_ROBOT_TERMS) and not has_any_term(haystack, INDUSTRIAL_CONTEXT_TERMS):
        return True
    if has_any_term(haystack, GENERAL_BUSINESS_PROFILE_TERMS) and not has_any_term(
        haystack,
        INDUSTRIAL_CONTEXT_TERMS | BUILT_ENVIRONMENT_TERMS,
    ):
        return True
    return False


def _source_tags(item: StoredNormalizedItem) -> set[str]:
    raw_tags = item.metadata.get("tags", [])
    return {str(tag).lower() for tag in raw_tags}


def is_broad_feed_source(item: StoredNormalizedItem) -> bool:
    return bool(item.metadata.get("broad_feed"))


def is_destatis_construction_statistics_signal(item: StoredNormalizedItem) -> bool:
    if item.source_id != "destatis_press_listing":
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return has_any_term(haystack, DESTATIS_CONSTRUCTION_STATISTICS_TERMS) and has_any_term(
        haystack, STATISTICAL_SIGNAL_TERMS
    )


def is_wood_central_timber_policy_signal(item: StoredNormalizedItem) -> bool:
    if item.source_id != "wood_central_api":
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return has_any_term(haystack, TIMBER_TERMS := {"timber", "mass timber", "clt", "glulam"}) and has_any_term(
        haystack, WOOD_CENTRAL_TIMBER_POLICY_TERMS
    )


def is_wood_central_timber_economics_signal(item: StoredNormalizedItem) -> bool:
    if item.source_id != "wood_central_api":
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    timber_terms = {"timber", "mass timber", "clt", "glulam"}
    return (
        has_any_term(haystack, timber_terms)
        and has_any_term(haystack, WOOD_CENTRAL_TIMBER_ECONOMICS_TERMS)
        and has_any_term(haystack, WOOD_CENTRAL_TIMBER_QUANTIFIED_TERMS)
        and has_any_term(haystack, WOOD_CENTRAL_TIMBER_COMMERCIAL_BARRIER_TERMS)
    )


def has_clear_all3_scope(item: StoredNormalizedItem, competitor_count: int, event_flags: dict[str, bool]) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    if competitor_count > 0:
        return True
    if event_flags.get("strategic_ai_major_deal_signal"):
        return True
    if event_flags.get("construction_statistics_signal"):
        return True
    if event_flags.get("timber_policy_signal"):
        return True
    if event_flags.get("timber_economics_signal"):
        return True
    if has_any_term(haystack, BROAD_FEED_SCOPE_TERMS):
        return True
    if event_flags.get("timber_strategic_signal"):
        return True
    if has_any_term(haystack, ROBOTICS_TERMS) and has_any_term(haystack, STRATEGIC_WORK_ENV_TERMS):
        return True
    if has_any_term(haystack, ROBOTICS_TERMS) and has_any_term(haystack, INDUSTRIAL_ROBOTICS_CONTEXT_TERMS):
        return True
    if has_any_term(haystack, AUTOMATION_TERMS) and has_any_term(haystack, {"industrial", "manufacturing", "factory"}):
        return True
    if has_any_term(haystack, WAREHOUSE_LOGISTICS_TERMS):
        return (
            has_any_term(haystack, BUILT_ENVIRONMENT_TERMS)
            or (
                has_any_term(haystack, ROBOTICS_TERMS)
                and has_any_term(haystack, {"industrial", "manufacturing", "factory"})
                and (
                    event_flags.get("deployment_event", False)
                    or event_flags.get("funding_event", False)
                    or event_flags.get("partnership_event", False)
                )
            )
        )
    return False


def has_topic_relevance(item: StoredNormalizedItem, competitor_count: int, event_flags: dict[str, bool]) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return competitor_count > 0 or has_any_term(haystack, TOPIC_TERMS) or any(event_flags.values())


def is_general_business_profile_noise(item: StoredNormalizedItem, event_flags: dict[str, bool]) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    if not has_any_term(haystack, GENERAL_BUSINESS_PROFILE_TERMS):
        return False
    return not any(
        (
            event_flags.get("industrial_robotics_signal", False),
            event_flags.get("construction_innovation_signal", False),
            event_flags.get("timber_strategic_signal", False),
            event_flags.get("permitting_or_code_signal", False),
            event_flags.get("factory_opening_or_expansion", False),
        )
    )


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
    if is_general_business_profile_noise(item, event_flags):
        return "drop", "general_business_profile_noise"
    if not has_clear_all3_scope(item, competitor_count, event_flags):
        return "drop", "no_clear_all3_scope"
    if is_broad_feed_source(item):
        haystack = f"{item.title} {item.text_preview or ''}"
        high_intent_scope = has_any_term(haystack, HIGH_INTENT_BROAD_FEED_TERMS)
        strong_broad_signal = (
            competitor_count > 0
            or event_flags.get("strategic_ai_major_deal_signal")
            or (event_flags.get("permitting_or_code_signal") and high_intent_scope)
            or event_flags.get("timber_strategic_signal")
            or (
                event_flags.get("quantified_scale_signal")
                and high_intent_scope
            )
            or (
                event_flags.get("funding_event")
                and (
                    high_intent_scope
                    or (
                        has_any_term(haystack, ROBOTICS_TERMS)
                        and has_any_term(haystack, STRATEGIC_WORK_ENV_TERMS)
                    )
                    or (
                        has_any_term(haystack, AUTOMATION_TERMS)
                        and has_any_term(haystack, {"industrial", "manufacturing", "factory"})
                    )
                )
            )
            or (
                event_flags.get("partnership_event")
                and high_intent_scope
                and (
                    has_any_term(haystack, ROBOTICS_TERMS)
                    or has_any_term(haystack, AUTOMATION_TERMS)
                )
            )
            or (
                event_flags.get("deployment_event")
                and (
                    has_any_term(haystack, ROBOTICS_TERMS)
                    or has_any_term(haystack, AUTOMATION_TERMS)
                )
                and (
                    high_intent_scope
                    or has_any_term(haystack, {"industrial", "manufacturing", "factory"})
                )
            )
            or (event_flags.get("factory_opening_or_expansion") and high_intent_scope)
        )
        if not strong_broad_signal:
            return "drop", "broad_feed_without_strong_signal"
    if not has_topic_relevance(item, competitor_count, event_flags):
        return "drop", "no_clear_topic_signal"
    return "keep", None
