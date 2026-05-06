"""Rule-based ranking for Bot 1."""

from __future__ import annotations

import re
from pathlib import Path

from all3_radar.config.loader import load_yaml
from all3_radar.domain.models import RankedDecision, StoredNormalizedItem
from all3_radar.pipeline.filters import (
    compute_relevance_status,
    is_construction_briefing_scope_signal,
    is_construction_news_intelligence_signal,
    is_destatis_construction_statistics_signal,
    is_housing_market_signal,
    is_interesting_engineering_scope_signal,
    is_wood_central_timber_economics_signal,
    is_wood_central_timber_policy_signal,
)

FUNDING_TERMS = (
    "raises",
    "raised",
    "series a",
    "series b",
    "series c",
    "series d",
    "seed round",
    "pre-seed",
    "funding round",
    "investment",
    "financing",
)
PARTNERSHIP_TERMS = ("partnership", "partners with", "partnered with", "partnered", "partnering", "collaboration")
ACQUISITION_TERMS = (
    "acquires",
    "acquisition",
    "acquired",
    "buys",
    "buying",
    "purchase",
    "purchases",
    "purchased",
    "takeover",
    "takeovers",
    "merger",
    "merge",
    "merged",
)
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
FACTORY_OPENING_VERBS = ("opens", "opened", "opening", "launches", "launched", "announces", "announced", "expands", "expanded")
FACTORY_CONTEXT_TERMS = (
    "factory",
    "factories",
    "production line",
    "production lines",
    "manufacturing facility",
    "manufacturing facilities",
    "manufacturing plant",
    "manufacturing plants",
    "hardware manufacturing",
    "production capacity",
    "capacity to build",
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
TIMBER_PERFORMANCE_TERMS = (
    "heat loss",
    "thermal bridges",
    "thermal bridge",
    "building performance",
    "energy performance",
    "operational energy",
    "cold zones",
    "identical typology",
    "embodied carbon",
    "concrete and steel",
    "concrete vs mass timber",
    "steel vs timber",
)
SHOWCASE_TIMBER_TERMS = ("showcase", "design", "architecture", "pavilion", "residence", "award")
CONSTRUCTION_INNOVATION_TERMS = ("modular", "prefab", "prefabrication", "offsite", "off-site", "factory-built")
ROBOTIC_TIMBER_FABRICATION_TERMS = (
    "robotic arm",
    "robot mills",
    "robotic fabrication",
    "robotic mass timber",
    "robotic timber",
    "robotic construction",
    "kuka",
    "milling",
    "millimetre precision",
    "millimeter precision",
)
ADAPTIVE_REUSE_HOUSING_DELIVERY_TERMS = (
    "olympic village",
    "student housing",
    "student accommodation",
    "students",
    "dormitory",
    "dormitories",
    "reopen to students",
    "converted",
    "converting",
    "conversion",
    "adaptive reuse",
    "four-month",
    "four months",
    "works programme",
    "publicly supported student housing",
)
NATIONAL_ROBOTICS_STRATEGY_TERMS = (
    "national strategy",
    "five-year plan",
    "15th five-year plan",
    "industrial system",
    "core of national strategy",
    "physical applications",
    "ifr reports",
    "international federation of robotics",
)
ROBOT_SAFETY_GOVERNANCE_TERMS = (
    "rulebook",
    "rulebooks",
    "rules conflict",
    "safer decisions",
    "safe decisions",
    "transparent decisions",
    "safety",
    "governance",
    "real-world situations",
    "real world situations",
)
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
    "drive-by-wire",
    "driverless",
    "mining truck",
    "haul truck",
    "autonomous haulage",
    "heavy equipment",
    "off-road",
    "mine site",
    "surface finishing",
    "data factory",
    "real-world data",
    "real world data",
)
HUMANOID_AFFORDABILITY_TERMS = (
    "entry-level",
    "lower-cost",
    "low-cost",
    "affordable",
    "price point",
    "globally",
    "global sales",
    "global availability",
    "aliexpress",
    "western peers",
    "broader market",
    "entry point",
    "experimentation",
)
HUMANOID_TERMS = ("humanoid", "humanoid robot", "humanoid robots", "droid")
LOW_PRICE_RE = re.compile(r"\$?\s?([1-9]\d{0,2}(?:,\d{3})+|\d{3,5})\b")
PRODUCT_LAUNCH_VERBS = (
    "launches",
    "launched",
    "unveils",
    "unveiled",
    "introduces",
    "introduced",
    "releases",
    "released",
    "updates",
    "updated",
    "rolls out",
    "rolled out",
    "debuts",
    "debuted",
)
PRODUCT_LAUNCH_NOUNS = (
    "product",
    "platform",
    "tool",
    "software",
    "system",
    "family",
    "cobot",
    "cobots",
    "robot",
    "robots",
    "controller",
    "assistant",
)
PRODUCT_OPERATIONAL_TERMS = (
    "robot cell",
    "robot cells",
    "scara",
    "3d vision",
    "machine vision",
    "physical robots",
    "programming platform",
    "cobot",
    "cobots",
    "automated guided vehicles",
    "agv",
    "agvs",
    "autonomous mobile robots",
    "mobile robot",
    "mobile robots",
    "factory",
    "factories",
    "production",
    "industrial tasks",
)
NON_FUNDING_RAISED_PHRASES = (
    "raised concerns",
    "raised fresh concerns",
    "raised questions",
    "raised alarms",
)
QUANTIFIED_SCALE_RE = re.compile(
    r"\b("
    r"\d+(\.\d+)?x|"
    r"\d+[,\d]*\s?(sqm|sq m|square metre|square meter|m2|square foot|square feet|sq ft|sqft|sf|percent|%)|"
    r"\$?\d+[,\d]*(\.\d+)?\s?(m|bn|billion|million)"
    r")\b"
)
BILLION_SCALE_RE = re.compile(
    r"\b("
    r"\$?\d+[,\d]*(\.\d+)?\s?(b|bn|billion)|"
    r"valued at\s+\$?\d+[,\d]*(\.\d+)?\s?(b|bn|billion)|"
    r"valuation\s+of\s+\$?\d+[,\d]*(\.\d+)?\s?(b|bn|billion)"
    r")\b"
)
WAREHOUSE_LOGISTICS_TERMS = ("warehouse", "logistics", "intralogistics", "material handling")
STRATEGIC_CONTEXT_TERMS = ("construction", "industrial", "manufacturing", "factory", "factories", "jobsite", "worksite", "assembly", "production")
AI_CORE_TERMS = (
    "ai",
    "artificial intelligence",
    "foundation model",
    "vision-language-action",
    "vla model",
    "physical ai",
    "physics ai",
)
AI_COMPANY_CONTEXT_TERMS = (
    "ai",
    "artificial intelligence",
    "physical ai",
    "physics ai",
    "startup",
    "startups",
    "company",
    "companies",
    "lab",
    "labs",
)
AI_COMPANY_MODEL_TERMS = (
    "model",
    "models",
    "platform",
    "platforms",
    "system",
    "systems",
)
PHYSICAL_INDUSTRY_AI_STRONG_TERMS = (
    "aerospace",
    "automotive",
    "advanced manufacturing",
    "manufacturing",
    "industrial",
    "robotics",
    "robot",
    "robots",
    "robotic interactions",
    "engineering workflows",
    "engineering software",
    "factory",
    "factories",
    "production",
    "materials",
    "industrial automation",
)
PHYSICAL_INDUSTRY_AI_WEAK_TERMS = (
    "engineering",
    "automation",
    "physical world",
    "drug discovery",
)
STRATEGIC_AI_PHYSICAL_TERMS = (
    "engineering",
    "engineering software",
    "manufacturing",
    "manufacturing workflow",
    "manufacturing workflows",
    "factory",
    "factories",
    "factory floor",
    "industrial automation",
    "robotics",
    "robot",
    "robots",
    "physical ai",
    "physics ai",
    "virtual twin",
    "virtual twins",
    "digital twin",
    "digital twins",
    "simulation",
    "industrial software",
    "robot programming",
)
MAJOR_DEAL_TERMS = (
    "valuation",
    "valued at",
    "strategic deal",
    "strategic merger",
)
STRATEGIC_CAPABILITY_TARGET_TERMS = (
    "robot",
    "robots",
    "robotics",
    "humanoid",
    "autonomous system",
    "autonomous systems",
    "physical ai",
    "physics ai",
    "industrial automation",
    "machine vision",
    "robot programming",
    "construction robotics",
    "construction automation",
    "prefab",
    "prefabrication",
    "modular",
    "offsite",
    "off-site",
    "contech",
    "building tech",
    "housing delivery",
    "mass timber",
    "timber",
)
STRATEGIC_CAPABILITY_COMPANY_TERMS = (
    "startup",
    "startups",
    "company",
    "companies",
    "platform",
    "platforms",
    "technology",
    "technologies",
    "software",
    "systems",
    "system",
    "developer",
    "developers",
    "capability",
    "capabilities",
    "ambitions",
)


def load_ranking_rules(path: Path) -> dict:
    return load_yaml(path)


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(_term_pattern(term).search(lowered) for term in terms)


def _count_matches(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if _term_pattern(term).search(lowered))


def derive_event_flags(item: StoredNormalizedItem) -> dict[str, bool]:
    haystack = f"{item.title} {item.text_preview or ''}".lower()
    timber_present = _contains_any(haystack, TIMBER_TERMS)
    quantified_scale = bool(QUANTIFIED_SCALE_RE.search(haystack))
    billion_scale = bool(BILLION_SCALE_RE.search(haystack))
    timber_strategic = timber_present and (_contains_any(haystack, TIMBER_STRATEGIC_TERMS) or quantified_scale)
    timber_performance = timber_present and _contains_any(haystack, TIMBER_PERFORMANCE_TERMS)
    adjacent_logistics_only = _contains_any(haystack, WAREHOUSE_LOGISTICS_TERMS) and not _contains_any(haystack, STRATEGIC_CONTEXT_TERMS)
    industrial_robotics_signal = (
        (_contains_any(haystack, ("robot", "robots", "robotics", "humanoid", "automation", "autonomous", "driverless")) and _contains_any(haystack, INDUSTRIAL_ROBOTICS_TERMS))
        or (_contains_any(haystack, ("robot", "robots", "robotics", "humanoid")) and _contains_any(haystack, STRATEGIC_CONTEXT_TERMS))
    )
    robotic_timber_fabrication_signal = (
        item.source_id == "wood_central_api"
        and timber_present
        and _contains_any(haystack, ROBOTIC_TIMBER_FABRICATION_TERMS)
        and (
            industrial_robotics_signal
            or _contains_any(haystack, ("robot", "robots", "robotic", "robotics", "automation"))
        )
    )
    adaptive_reuse_housing_delivery_signal = (
        item.source_id == "wood_central_api"
        and timber_present
        and _contains_any(haystack, ADAPTIVE_REUSE_HOUSING_DELIVERY_TERMS)
        and _contains_any(haystack, ("student housing", "student accommodation", "students", "housing", "accommodation"))
        and _contains_any(haystack, ("four months", "four-month", "reopen", "converted", "converting", "conversion"))
    )
    national_robotics_strategy_signal = (
        bool(item.metadata.get("broad_feed"))
        and _contains_any(haystack, ("robot", "robots", "robotics", "ai-powered robots", "physical ai"))
        and _contains_any(haystack, NATIONAL_ROBOTICS_STRATEGY_TERMS)
    )
    robot_safety_governance_signal = (
        _contains_any(haystack, ("robot", "robots", "robotics", "autonomous robots", "autonomous systems"))
        and _contains_any(haystack, ROBOT_SAFETY_GOVERNANCE_TERMS)
        and _contains_any(haystack, ("real-world", "real world", "rules conflict", "transparent", "decisions", "safety"))
    )
    low_price_match = LOW_PRICE_RE.search(haystack)
    low_price_value = None
    if low_price_match:
        try:
            low_price_value = int(low_price_match.group(1).replace(",", ""))
        except ValueError:
            low_price_value = None
    humanoid_affordability_signal = (
        _contains_any(haystack, HUMANOID_TERMS)
        and low_price_value is not None
        and low_price_value <= 10000
        and _contains_any(haystack, HUMANOID_AFFORDABILITY_TERMS)
    )
    construction_innovation_signal = quantified_scale and _contains_any(haystack, CONSTRUCTION_INNOVATION_TERMS)
    construction_statistics_signal = is_destatis_construction_statistics_signal(item)
    housing_market_signal = is_housing_market_signal(item)
    timber_policy_signal = is_wood_central_timber_policy_signal(item)
    timber_economics_signal = is_wood_central_timber_economics_signal(item)
    construction_briefing_scope_signal = is_construction_briefing_scope_signal(item)
    construction_news_intelligence_signal = is_construction_news_intelligence_signal(item)
    interesting_engineering_scope_signal = is_interesting_engineering_scope_signal(item)
    funding_event = _contains_any(haystack, FUNDING_TERMS) and not _contains_any(haystack, NON_FUNDING_RAISED_PHRASES)
    acquisition_event = _contains_any(haystack, ACQUISITION_TERMS)
    partnership_event = _contains_any(haystack, PARTNERSHIP_TERMS)
    ai_company_context = _contains_any(haystack, AI_COMPANY_CONTEXT_TERMS) or (
        funding_event and _contains_any(haystack, AI_COMPANY_MODEL_TERMS)
    )
    weak_physical_industry_count = _count_matches(haystack, PHYSICAL_INDUSTRY_AI_WEAK_TERMS)
    physical_industry_ai_megafunding_signal = (
        ai_company_context
        and (
            funding_event
            or billion_scale
        )
        and (
            _contains_any(haystack, PHYSICAL_INDUSTRY_AI_STRONG_TERMS)
            or (
                billion_scale
                and weak_physical_industry_count >= 2
            )
        )
    )
    product_launch_event = (
        _contains_any(haystack, PRODUCT_LAUNCH_VERBS)
        and _contains_any(haystack, PRODUCT_LAUNCH_NOUNS)
        and (
            industrial_robotics_signal
            or construction_innovation_signal
            or _contains_any(haystack, PRODUCT_OPERATIONAL_TERMS)
        )
    )
    strategic_ai_major_deal_signal = (
        bool(item.metadata.get("broad_feed"))
        and _contains_any(haystack, AI_CORE_TERMS)
        and _contains_any(haystack, STRATEGIC_AI_PHYSICAL_TERMS)
        and (
            (funding_event and (quantified_scale or _contains_any(haystack, MAJOR_DEAL_TERMS)))
            or (acquisition_event and (quantified_scale or _contains_any(haystack, MAJOR_DEAL_TERMS)))
            or (partnership_event and quantified_scale and _contains_any(haystack, ("strategic",)))
        )
    )
    strategic_capability_acquisition_signal = acquisition_event and _contains_any(
        haystack, STRATEGIC_CAPABILITY_TARGET_TERMS
    ) and (
        _contains_any(haystack, STRATEGIC_CAPABILITY_COMPANY_TERMS)
        or _contains_any(haystack, STRATEGIC_CONTEXT_TERMS)
        or _contains_any(haystack, ("ai", "artificial intelligence"))
    )
    factory_opening_or_expansion = _contains_any(haystack, FACTORY_TERMS) or (
        _contains_any(haystack, FACTORY_OPENING_VERBS) and _contains_any(haystack, FACTORY_CONTEXT_TERMS)
    )
    return {
        "funding_event": funding_event,
        "partnership_event": partnership_event,
        "product_launch_event": product_launch_event,
        "acquisition_event": acquisition_event,
        "deployment_event": _contains_any(haystack, DEPLOYMENT_TERMS),
        "factory_opening_or_expansion": factory_opening_or_expansion,
        "permitting_or_code_signal": _contains_any(haystack, POLICY_TERMS),
        "quantified_scale_signal": quantified_scale,
       "timber_strategic_signal": timber_strategic,
        "timber_performance_signal": timber_performance,
        "industrial_robotics_signal": industrial_robotics_signal,
        "robotic_timber_fabrication_signal": robotic_timber_fabrication_signal,
        "adaptive_reuse_housing_delivery_signal": adaptive_reuse_housing_delivery_signal,
        "national_robotics_strategy_signal": national_robotics_strategy_signal,
        "robot_safety_governance_signal": robot_safety_governance_signal,
        "humanoid_affordability_signal": humanoid_affordability_signal,
        "construction_innovation_signal": construction_innovation_signal,
        "construction_statistics_signal": construction_statistics_signal,
        "housing_market_signal": housing_market_signal,
        "construction_news_intelligence_signal": construction_news_intelligence_signal,
        "timber_policy_signal": timber_policy_signal,
        "timber_economics_signal": timber_economics_signal,
        "construction_briefing_scope_signal": construction_briefing_scope_signal,
        "interesting_engineering_scope_signal": interesting_engineering_scope_signal,
        "strategic_ai_major_deal_signal": strategic_ai_major_deal_signal,
        "strategic_capability_acquisition_signal": strategic_capability_acquisition_signal,
        "physical_industry_ai_megafunding_signal": physical_industry_ai_megafunding_signal,
        "showcase_only_architecture_penalty": timber_present
        and _contains_any(haystack, SHOWCASE_TIMBER_TERMS)
        and not timber_strategic
        and not adaptive_reuse_housing_delivery_signal,
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
    if item.source_id == "destatis_press_listing":
        score += signals["official_statistics_source"]
        applied_signals["official_statistics_source"] = signals["official_statistics_source"]
    if item.source_id == "wood_central_api":
        score += signals["direct_wood_central_source"]
        applied_signals["direct_wood_central_source"] = signals["direct_wood_central_source"]
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
