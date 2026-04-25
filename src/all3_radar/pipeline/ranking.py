"""Rule-based ranking for Bot 1."""

from __future__ import annotations

import re
from pathlib import Path

from all3_radar.config.loader import load_yaml
from all3_radar.domain.models import RankedDecision, StoredNormalizedItem
from all3_radar.pipeline.filters import compute_relevance_status

FUNDING_TERMS = ("funding", "raises", "raised", "series a", "series b", "seed round", "investment", "pre-seed", "ipo")
PARTNERSHIP_TERMS = ("partnership", "partners with", "partnered with", "partnering", "collaboration")
ACQUISITION_TERMS = ("acquires", "acquisition", "acquired")
DEPLOYMENT_TERMS = ("deployment", "deployed", "pilot", "rollout", "contract", "framework agreement")
FACTORY_TERMS = (
    "factory opening",
    "factory expansion",
    "new factory",
    "production line",
    "manufacturing facility",
    "manufacturing plant",
    "plant expansion",
    "capacity expansion",
)
POLICY_TERMS = (
    "permitting",
    "permit",
    "building code",
    "code approval",
    "approval pathway",
    "planning approval",
    "regulation",
    "regulatory",
    "zoning",
    "standard",
    "policy reform",
)
TIMBER_TERMS = ("timber", "mass timber", "glulam", "clt")
TIMBER_STRATEGIC_TERMS = ("demand", "adoption", "floor area", "square metre", "sq m", "growth", "capacity")
SHOWCASE_TIMBER_TERMS = ("showcase", "design", "architecture", "pavilion", "residence", "award")
CONSTRUCTION_INNOVATION_TERMS = ("modular", "prefab", "prefabrication", "offsite", "off-site", "factory-built")
INDUSTRIAL_ROBOTICS_TERMS = (
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
)
QUANTIFIED_SCALE_RE = re.compile(
    r"\b("
    r"\d+(\.\d+)?x|"
    r"\d+[,\d]*\s?(sqm|sq m|square metre|square meter|m2|square foot|square feet|sq ft|sqft|sf|percent|%)|"
    r"\$?\d+[,\d]*(\.\d+)?\s?(m|bn|billion|million)"
    r")\b"
)
WAREHOUSE_LOGISTICS_TERMS = ("warehouse", "logistics", "intralogistics", "material handling")
STRATEGIC_CONTEXT_TERMS = ("construction", "industrial", "manufacturing", "factory", "factories", "jobsite", "worksite", "assembly", "production")


def load_ranking_rules(path: Path) -> dict:
    return load_yaml(path)


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(_term_pattern(term).search(lowered) for term in terms)


def derive_event_flags(item: StoredNormalizedItem) -> dict[str, bool]:
    haystack = f"{item.title} {item.text_preview or ''}".lower()
    timber_present = _contains_any(haystack, TIMBER_TERMS)
    quantified_scale = bool(QUANTIFIED_SCALE_RE.search(haystack))
    timber_strategic = timber_present and (_contains_any(haystack, TIMBER_STRATEGIC_TERMS) or quantified_scale)
    adjacent_logistics_only = _contains_any(haystack, WAREHOUSE_LOGISTICS_TERMS) and not _contains_any(haystack, STRATEGIC_CONTEXT_TERMS)
    industrial_robotics_signal = (
        (_contains_any(haystack, ("robot", "robots", "robotics", "humanoid", "automation", "autonomous")) and _contains_any(haystack, INDUSTRIAL_ROBOTICS_TERMS))
        or (_contains_any(haystack, ("robot", "robots", "robotics", "humanoid")) and _contains_any(haystack, STRATEGIC_CONTEXT_TERMS))
    )
    construction_innovation_signal = quantified_scale and _contains_any(haystack, CONSTRUCTION_INNOVATION_TERMS)
    return {
        "funding_event": _contains_any(haystack, FUNDING_TERMS),
        "partnership_event": _contains_any(haystack, PARTNERSHIP_TERMS),
        "acquisition_event": _contains_any(haystack, ACQUISITION_TERMS),
        "deployment_event": _contains_any(haystack, DEPLOYMENT_TERMS),
        "factory_opening_or_expansion": _contains_any(haystack, FACTORY_TERMS),
        "permitting_or_code_signal": _contains_any(haystack, POLICY_TERMS),
        "quantified_scale_signal": quantified_scale,
        "timber_strategic_signal": timber_strategic,
        "industrial_robotics_signal": industrial_robotics_signal,
        "construction_innovation_signal": construction_innovation_signal,
        "showcase_only_architecture_penalty": timber_present
        and _contains_any(haystack, SHOWCASE_TIMBER_TERMS)
        and not timber_strategic,
        "consumer_robotics_penalty": False,
        "adjacent_logistics_only": adjacent_logistics_only,
    }


def rank_item(
    item: StoredNormalizedItem,
    competitor_count: int,
    freshness_is_fresh: bool,
    ranking_rules: dict,
) -> RankedDecision:
    signals = ranking_rules["signals"]
    thresholds = ranking_rules["thresholds"]
    event_flags = derive_event_flags(item)
    relevance_status, base_skip_reason = compute_relevance_status(item, competitor_count, freshness_is_fresh, event_flags)

    score = 0
    applied_signals: dict[str, int | bool | str | list[str]] = {}

    if item.layer.value == "direct":
        score += signals["direct_source"]
        applied_signals["direct_source"] = signals["direct_source"]
    if item.is_wrapper and item.layer.value == "google_competitor":
        score += signals["google_competitor_wrapper"]
        applied_signals["google_competitor_wrapper"] = signals["google_competitor_wrapper"]
    if competitor_count:
        score += signals["competitor_mention"]
        applied_signals["competitor_mention"] = competitor_count

    for flag_name, flag_value in event_flags.items():
        if not flag_value:
            continue
        if flag_name in signals:
            score += signals[flag_name]
            applied_signals[flag_name] = signals[flag_name]
        else:
            applied_signals[flag_name] = True

    is_shortlisted = relevance_status == "keep" and freshness_is_fresh and score >= thresholds["shortlist_min_score"]
    is_borderline = relevance_status == "keep" and freshness_is_fresh and score >= max(0, thresholds["shortlist_min_score"] - 6)
    send_status = "stored_only"
    skip_reason = base_skip_reason
    if relevance_status == "drop":
        send_status = "skip"
    elif score < thresholds["send_min_score"]:
        send_status = "stored_only"

    return RankedDecision(
        relevance_status=relevance_status,
        send_status=send_status,
        skip_reason=skip_reason,
        score=score,
        signals={
            "competitor_count": competitor_count,
            "event_flags": event_flags,
            "applied_signals": applied_signals,
        },
        is_shortlisted=is_shortlisted,
        is_borderline=is_borderline,
    )
