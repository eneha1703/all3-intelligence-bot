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
    "data factory",
    "real-world data",
    "real world data",
    "drive-by-wire",
    "driverless",
    "haul truck",
    "mining truck",
    "heavy equipment",
    "mine site",
    "surface finishing",
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
STRATEGIC_AI_REAL_WORLD_TERMS = (
    "physical ai",
    "physics ai",
    "robotics",
    "robot",
    "robots",
    "virtual twin",
    "virtual twins",
    "digital twin",
    "digital twins",
    "manufacturing workflow",
    "manufacturing workflows",
    "production workflow",
    "production workflows",
    "engineering workflow",
    "engineering workflows",
    "physical industries",
    "factory floor",
)
STRATEGIC_CAPABILITY_ACQUISITION_TERMS = (
    "robot",
    "robots",
    "robotics",
    "humanoid",
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
)
HUMANOID_ACCESS_TERMS = (
    "humanoid",
    "aliexpress",
    "global sales",
    "global availability",
    "broader market",
    "entry point",
    "western peers",
    "experimentation",
    "entry-level",
    "low-cost",
    "lower-cost",
)
DESTATIS_CONSTRUCTION_MARKET_TERMS = (
    "bauhauptgewerbe",
    "auftragseingang",
    "baugenehmigungen",
    "construction orders",
    "building permits",
    "housing approvals",
    "construction output",
    "orders",
    "permits",
    "approvals",
    "output",
)
HOUSING_MARKET_CONTEXT_TERMS = (
    "housing market",
    "wohnungsmarkt",
    "housebuilding",
    "wohnungsbau",
    "rents",
    "mieten",
    "house prices",
    "kaufpreise",
    "immobilienfinanzierung",
    "immobilienfinanzierungsindex",
    "finanzierungsindex",
    "difi",
    "zinsen",
    "real estate finance",
    "property finance",
    "affordable housing",
    "build-to-rent",
    "btr",
    "residential demand",
    "housing supply",
    "building permits",
    "housing approvals",
    "energieeffizienz",
)
HOUSING_MARKET_QUANTIFIED_TERMS = (
    "%",
    "index",
    "study",
    "report",
    "forecast",
    "shortfall",
    "shortage",
    "higher",
    "lower",
    "increase",
    "decrease",
    "rise",
    "fall",
)
UK_CONSTRUCTION_MARKET_CONTEXT_TERMS = (
    "construction activity",
    "construction output",
    "project starts",
    "main contract awards",
    "planning approvals",
    "planning applications",
    "construction sector",
    "infrastructure",
    "commercial",
    "housing",
    "industrial",
    "regional",
    "materials prices",
    "workforce",
    "labour costs",
)
UK_CONSTRUCTION_MARKET_QUANTIFIED_TERMS = (
    "%",
    "index",
    "report",
    "forecast",
    "fall",
    "fell",
    "drop",
    "decline",
    "rise",
    "rose",
    "increase",
    "higher",
    "lower",
)
ROBOT_AI_TRAINING_INFRASTRUCTURE_TERMS = (
    "data factory",
    "train robot ai",
    "training robot ai",
    "robot ai",
    "real-world data",
    "real world data",
    "real-world autonomy",
    "real world autonomy",
    "mobile manipulator",
)
HEAVY_INDUSTRIAL_AUTONOMY_TERMS = (
    "drive-by-wire",
    "driverless",
    "mining truck",
    "haul truck",
    "autonomous haulage",
    "heavy equipment",
    "mine site",
    "off-road",
)
ROBOTIC_TIMBER_FABRICATION_TERMS = (
    "robotic arm",
    "robot mills",
    "robotic fabrication",
    "robotic mass timber",
    "robotic timber",
    "kuka",
    "milling",
    "precision",
)
ADAPTIVE_REUSE_HOUSING_DELIVERY_TERMS = (
    "olympic village",
    "student housing",
    "student accommodation",
    "reopen to students",
    "converted",
    "converting",
    "conversion",
    "four-month",
    "four months",
    "publicly supported student housing",
)
NATIONAL_ROBOTICS_STRATEGY_TERMS = (
    "national strategy",
    "five-year plan",
    "industrial system",
    "physical applications",
    "international federation of robotics",
)
ROBOT_SAFETY_GOVERNANCE_TERMS = (
    "rulebook",
    "rulebooks",
    "rules conflict",
    "safer decisions",
    "transparent decisions",
    "real-world situations",
    "real world situations",
)
WOOD_CENTRAL_HARD_CONSTRAINT_TERMS = (
    "cap",
    "height cap",
    "height limit",
    "approval",
    "approvals",
    "approval pathway",
    "permitting",
    "permit",
    "insurance",
    "insurers",
    "fire",
    "restriction",
    "restrictions",
    "barrier",
    "barriers",
)
WOOD_CENTRAL_POLICY_CONTEXT_TERMS = (
    "code",
    "codes",
    "standard",
    "standards",
    "regulation",
    "regulations",
    "regulatory",
    "policy",
    "policies",
)
WOOD_CENTRAL_ECONOMICS_CONTEXT_TERMS = (
    "premium",
    "premiums",
    "cost",
    "costs",
    "price",
    "prices",
    "pricing",
    "economics",
    "economic",
    "viability",
    "commercial viability",
    "competitiveness",
    "affordability",
)
WOOD_CENTRAL_QUANTIFIED_ECONOMICS_TERMS = (
    "%",
    "times higher",
    "times lower",
    "six to ten times",
    "higher than",
    "lower than",
)
WOOD_CENTRAL_PERFORMANCE_CONTEXT_TERMS = (
    "heat loss",
    "thermal bridges",
    "thermal bridge",
    "building performance",
    "energy performance",
    "operational energy",
    "cold zones",
    "identical typology",
)
WOOD_CENTRAL_MATERIAL_COMPARISON_TERMS = (
    "concrete",
    "steel",
    "mass timber",
    "clt",
    "glulam",
)
WOOD_CENTRAL_QUANTIFIED_PERFORMANCE_TERMS = (
    "%",
    "per cent",
    "more heat",
    "less heat",
    "higher than",
    "lower than",
)
WOOD_CENTRAL_FRICTION_TERMS = (
    "concern",
    "concerns",
    "challenge",
    "challenges",
    "conflict",
    "friction",
    "restrict",
    "restricted",
    "restriction",
    "restriction",
    "limit",
    "limits",
    "cap",
    "caps",
    "open new front",
)
WOOD_CENTRAL_COMMERCIAL_BARRIER_TERMS = (
    "barrier",
    "barriers",
    "adoption",
    "commercial",
    "competitive",
    "scaling",
    "scale-up",
    "viable",
    "viability",
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


def _source_extra(item: StoredNormalizedItem, key: str) -> str | None:
    value = item.metadata.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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
    official_construction_market_signal = (
        item.source_id == "destatis_press_listing"
        and event_flags.get("construction_statistics_signal", False)
        and _contains_any(haystack, DESTATIS_CONSTRUCTION_MARKET_TERMS)
    )
    housing_market_alert_signal = (
        _source_extra(item, "market_scope") in {"germany_housing_market", "uk_housing_market"}
        and event_flags.get("housing_market_signal", False)
        and _contains_any(haystack, HOUSING_MARKET_CONTEXT_TERMS)
        and _contains_any(haystack, HOUSING_MARKET_QUANTIFIED_TERMS)
    )
    uk_construction_market_alert_signal = (
        _source_extra(item, "market_scope") == "uk_construction_market"
        and event_flags.get("construction_news_intelligence_signal", False)
        and _contains_any(haystack, UK_CONSTRUCTION_MARKET_CONTEXT_TERMS)
        and _contains_any(haystack, UK_CONSTRUCTION_MARKET_QUANTIFIED_TERMS)
    )
    # Ranking already computes this narrowly from low humanoid price + affordability/access language.
    # At editorial time the RSS preview is often shorter, so trust the derived signal instead of
    # requiring the excerpt to repeat AliExpress/global-availability details.
    humanoid_access_signal = bool(event_flags.get("humanoid_affordability_signal", False)) and (
        _contains_any(haystack, HUMANOID_ACCESS_TERMS) or item.source_id == "interesting_engineering_rss"
    )
    timber_adoption_barrier_signal = (
        item.source_id == "wood_central_api"
        and event_flags.get("timber_policy_signal", False)
        and (
            _contains_any(haystack, WOOD_CENTRAL_HARD_CONSTRAINT_TERMS)
            or (
                _contains_any(haystack, WOOD_CENTRAL_POLICY_CONTEXT_TERMS)
                and _contains_any(haystack, WOOD_CENTRAL_FRICTION_TERMS)
            )
        )
    )
    timber_economics_alert_signal = (
        item.source_id == "wood_central_api"
        and event_flags.get("timber_economics_signal", False)
        and _contains_any(haystack, WOOD_CENTRAL_ECONOMICS_CONTEXT_TERMS)
        and _contains_any(haystack, WOOD_CENTRAL_QUANTIFIED_ECONOMICS_TERMS)
        and _contains_any(haystack, WOOD_CENTRAL_COMMERCIAL_BARRIER_TERMS)
    )
    timber_performance_alert_signal = (
        item.source_id == "wood_central_api"
        and event_flags.get("timber_performance_signal", False)
        and _contains_any(haystack, WOOD_CENTRAL_PERFORMANCE_CONTEXT_TERMS)
        and _contains_any(haystack, WOOD_CENTRAL_MATERIAL_COMPARISON_TERMS)
        and _contains_any(haystack, WOOD_CENTRAL_QUANTIFIED_PERFORMANCE_TERMS)
    )
    strategic_industrial_ai_alert_signal = (
        bool(item.metadata.get("broad_feed"))
        and event_flags.get("strategic_ai_major_deal_signal", False)
        and event_flags.get("funding_event", False)
        and _contains_any(haystack, STRATEGIC_AI_REAL_WORLD_TERMS)
    )
    strategic_capability_acquisition_alert_signal = (
        event_flags.get("strategic_capability_acquisition_signal", False)
        and event_flags.get("acquisition_event", False)
        and _contains_any(haystack, STRATEGIC_CAPABILITY_ACQUISITION_TERMS)
    )
    robot_ai_training_infrastructure_signal = (
        event_flags.get("industrial_robotics_signal", False)
        and _contains_any(haystack, ROBOT_AI_TRAINING_INFRASTRUCTURE_TERMS)
        and (
            operational_detail
            or event_flags.get("quantified_scale_signal", False)
            or "100 " in haystack
        )
    )
    heavy_industrial_autonomy_signal = (
        _contains_any(haystack, HEAVY_INDUSTRIAL_AUTONOMY_TERMS)
        and (
            event_flags.get("industrial_robotics_signal", False)
            or event_flags.get("interesting_engineering_scope_signal", False)
        )
        and (
            event_flags.get("deployment_event", False)
            or event_flags.get("product_launch_event", False)
            or event_flags.get("quantified_scale_signal", False)
            or _contains_any(haystack, ("introduced", "introduces", "unveiled", "unveils", "launches", "launched"))
        )
    )
    robotic_timber_fabrication_signal = (
        item.source_id == "wood_central_api"
        and event_flags.get("robotic_timber_fabrication_signal", False)
        and _contains_any(haystack, ROBOTIC_TIMBER_FABRICATION_TERMS)
    )
    adaptive_reuse_housing_delivery_signal = (
        item.source_id == "wood_central_api"
        and event_flags.get("adaptive_reuse_housing_delivery_signal", False)
        and _contains_any(haystack, ADAPTIVE_REUSE_HOUSING_DELIVERY_TERMS)
    )
    national_robotics_strategy_signal = (
        event_flags.get("national_robotics_strategy_signal", False)
        and _contains_any(haystack, NATIONAL_ROBOTICS_STRATEGY_TERMS)
    )
    robot_safety_governance_signal = (
        event_flags.get("robot_safety_governance_signal", False)
        and _contains_any(haystack, ROBOT_SAFETY_GOVERNANCE_TERMS)
    )
    tangible_operational_signal = operational_detail or construction_execution or industrial_relevance
    product_or_platform_news = product_launch and tangible_operational_signal and (
        industrial_relevance or construction_execution or competitor_count > 0
    )
    telegram_worthy = (
        (hard_news_event and tangible_operational_signal and not adjacent_logistics_only)
        or product_or_platform_news
        or (construction_execution and event_flags.get("quantified_scale_signal", False))
        or official_construction_market_signal
        or housing_market_alert_signal
        or uk_construction_market_alert_signal
        or humanoid_access_signal
        or timber_adoption_barrier_signal
        or timber_economics_alert_signal
        or timber_performance_alert_signal
        or strategic_industrial_ai_alert_signal
        or strategic_capability_acquisition_alert_signal
        or robot_ai_training_infrastructure_signal
        or heavy_industrial_autonomy_signal
        or robotic_timber_fabrication_signal
        or adaptive_reuse_housing_delivery_signal
        or national_robotics_strategy_signal
        or robot_safety_governance_signal
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
        "official_construction_market_signal": official_construction_market_signal,
        "housing_market_alert_signal": housing_market_alert_signal,
        "uk_construction_market_alert_signal": uk_construction_market_alert_signal,
        "humanoid_access_signal": humanoid_access_signal,
        "timber_adoption_barrier_signal": timber_adoption_barrier_signal,
        "timber_economics_alert_signal": timber_economics_alert_signal,
        "timber_performance_alert_signal": timber_performance_alert_signal,
        "strategic_industrial_ai_alert_signal": strategic_industrial_ai_alert_signal,
        "strategic_capability_acquisition_alert_signal": strategic_capability_acquisition_alert_signal,
        "robot_ai_training_infrastructure_signal": robot_ai_training_infrastructure_signal,
        "heavy_industrial_autonomy_signal": heavy_industrial_autonomy_signal,
        "robotic_timber_fabrication_signal": robotic_timber_fabrication_signal,
        "adaptive_reuse_housing_delivery_signal": adaptive_reuse_housing_delivery_signal,
        "national_robotics_strategy_signal": national_robotics_strategy_signal,
        "robot_safety_governance_signal": robot_safety_governance_signal,
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
    if event_flags.get("strategic_ai_major_deal_signal", False) and not strategic_industrial_ai_alert_signal:
        return EditorialDecision(
            allow_send=False,
            reason="editorial_strategic_ai_deal_stored_only",
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
