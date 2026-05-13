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
CONSUMER_AV_SERVICE_TERMS = {
    "robotaxi",
    "robotaxi service",
    "autonomous taxi",
    "self-driving taxi",
    "ride-hailing",
    "ride hailing",
    "ride service",
    "ride-sharing",
    "ridesharing",
    "autonomous ride service",
    "self-driving ride service",
    "public rides",
}
CONSUMER_AV_GUIDE_TERMS = {
    "how to ride",
    "costs",
    "cost to ride",
    "crash record",
    "where available",
    "available in",
    "ride in",
    "book a ride",
    "hail a ride",
    "app-based",
    "ride app",
    "city expansion",
    "service availability",
    "public ride",
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
PHARMA_BIOTECH_PRODUCTION_TERMS = {
    "cancer drug",
    "cancer drugs",
    "drug manufacturing",
    "pharmaceutical manufacturing",
    "pharma manufacturing",
    "pharmaceutical",
    "pharmaceuticals",
    "pharma",
    "biotech",
    "biotech therapeutics",
    "therapeutic production",
    "clinical production",
    "medical production",
    "drug production",
    "pharmaceutical production",
    "therapeutic manufacturing",
    "biopharma",
    "biopharmaceutical",
    "biopharmaceuticals",
    "therapeutics",
    "drug discovery",
}
SPACE_BIOTECH_TERMS = {
    "in-space drug manufacturing",
    "orbital pharma",
    "space biotech",
    "space pharma",
    "microgravity drug",
    "microgravity pharmaceutical",
    "microgravity therapeutics",
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
ROBOTICS_FACTORY_SIGNAL_TERMS = {
    "factory",
    "factories",
    "manufacturing",
    "production line",
    "production lines",
    "manufacturing line",
    "manufacturing lines",
    "manufacturing facility",
    "manufacturing facilities",
    "hardware manufacturing",
    "vertically integrated",
    "capacity to build",
}
INDUSTRIAL_AUTONOMY_EXCEPTION_TERMS = INDUSTRIAL_CONTEXT_TERMS | {
    "warehouse",
    "warehousing",
    "logistics",
    "intralogistics",
    "material handling",
    "autonomous mobile robots",
    "mobile industrial robots",
    "amr",
    "amrs",
    "agv",
    "agvs",
    "construction automation",
    "construction autonomy",
    "jobsite robotics",
    "off-road",
    "mining",
    "mine site",
    "heavy equipment",
    "earthmoving",
    "haul truck",
    "autonomous haulage",
    "infrastructure automation",
    "data center construction",
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
INDUSTRIAL_ROBOTICS_PRODUCT_LAUNCH_TERMS = {
    "launches",
    "launched",
    "introduces",
    "introduced",
    "unveils",
    "unveiled",
    "releases",
    "released",
    "rolls out",
    "rolled out",
    "debuts",
    "debuted",
}
INDUSTRIAL_ROBOTICS_PRODUCT_CONTEXT_TERMS = {
    "automation cell",
    "robot cell",
    "robotic cell",
    "surface finishing",
    "finishing cell",
    "sanding",
    "polishing",
    "grinding",
    "painting",
    "coating",
    "manufacturing cell",
    "factory automation",
    "industrial automation",
    "manufacturing automation",
    "autonomous cell",
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
ROBOTICS_BUSINESS_ENTITY_TERMS = {
    "teradyne robotics",
    "universal robots",
    "mobile industrial robots",
    "mir",
    "robotics revenue",
    "robotics segment revenue",
    "robotics segment",
    "collaborative robots",
    "cobots",
    "mobile robots",
    "amrs",
    "autonomous mobile robots",
}
ROBOTICS_BUSINESS_PERFORMANCE_TERMS = {
    "revenue",
    "sales",
    "orders",
    "margin",
    "earnings",
    "quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "segment",
    "growth",
    "grew",
    "decline",
    "declined",
    "rises",
    "rose",
    "falls",
    "fell",
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
TIMBER_LOGISTICS_OFF_SCOPE_TERMS = {
    "marine terminal",
    "port",
    "ports",
    "terminal",
    "timber terminal",
    "one-stop-shop",
    "one-stop shop",
    "logistics",
    "distribution",
    "shipping",
    "export hub",
    "import hub",
    "supply chain",
}
TIMBER_CONSTRUCTION_KEEP_TERMS = {
    "construction",
    "building",
    "buildings",
    "project",
    "projects",
    "development",
    "developments",
    "housing",
    "homes",
    "apartment",
    "apartments",
    "tower",
    "campus",
    "jobsite",
    "worksite",
    "site",
    "new homes",
    "modular housing",
    "factory-built housing",
}
GERMANY_HOUSING_MARKET_TERMS = {
    "wohnungsmarkt",
    "wohnungsbau",
    "wohnungsmangel",
    "wohnungsnot",
    "wohnungen",
    "überbelegten wohnungen",
    "uberbelegten wohnungen",
    "overcrowded dwellings",
    "overcrowded housing",
    "mieten",
    "mietpreis",
    "mietpreise",
    "kaufpreise",
    "hauspreise",
    "baugenehmigungen",
    "wohnungsbestand",
    "energieeffizienz",
    "investoren",
    "immobilienfinanzierung",
    "immobilienfinanzierungsindex",
    "finanzierungsindex",
    "difi",
    "zinsen",
    "zinssatz",
    "neubau",
    "residential market",
    "housing market",
    "real estate finance",
    "property finance",
    "building permits",
    "housing approvals",
    "rents",
    "house prices",
    "apartment market",
    "affordable housing",
}
UK_HOUSING_MARKET_TERMS = {
    "housing market",
    "housebuilding",
    "homebuilding",
    "housing delivery",
    "housing shortage",
    "affordable housing",
    "build-to-rent",
    "btr",
    "residential market",
    "rents",
    "rental market",
    "house prices",
    "planning reform",
    "planning system",
    "planning approvals",
    "residential demand",
    "housing supply",
    "starts",
    "completions",
}
UK_CONSTRUCTION_MARKET_TERMS = {
    "construction activity",
    "construction output",
    "project starts",
    "main contract awards",
    "planning approvals",
    "starts on site",
    "planning applications",
    "construction sector",
    "industry output",
    "materials prices",
    "workforce",
    "regional",
    "housing",
    "infrastructure",
    "industrial",
    "commercial",
    "civils",
    "engineering order books",
    "productivity",
    "labour costs",
}
UK_CONSTRUCTION_PRIORITY_TERMS = {
    "activity",
    "output",
    "housing",
    "residential",
    "infrastructure",
    "industrial",
    "inflation",
    "materials prices",
    "material prices",
    "labour costs",
    "labor costs",
    "planning approvals",
    "planning applications",
    "timber",
    "mass timber",
    "modular",
    "prefab",
    "prefabrication",
    "framework",
    "procurement",
    "demolition",
}
UK_CONSTRUCTION_PROGRAMME_TERMS = {
    "framework",
    "framework launched",
    "housing framework",
    "public-sector procurement",
    "public sector procurement",
    "procurement",
    "demolition",
}
UK_CONSTRUCTION_OFF_SCOPE_SECTOR_TERMS = {
    "hotel",
    "hotels",
    "leisure",
}
MARKET_SIGNAL_TERMS = {
    "%",
    "index",
    "finanzierungsindex",
    "immobilienfinanzierungsindex",
    "difi",
    "study",
    "report",
    "forecast",
    "fall",
    "fell",
    "drop",
    "decline",
    "declined",
    "rise",
    "rose",
    "increase",
    "increased",
    "higher",
    "lower",
    "shortfall",
    "shortage",
    "demand",
    "supply",
    "investor",
    "investors",
}
CONSTRUCTION_BRIEFING_SCOPE_TERMS = {
    "mass timber",
    "timber",
    "clt",
    "glulam",
    "modular",
    "prefab",
    "prefabrication",
    "offsite",
    "off-site",
    "industrialized construction",
    "factory-built housing",
    "construction robotics",
    "jobsite robotics",
    "construction automation",
    "housing delivery",
    "building permits",
    "planning reform",
}
INTERESTING_ENGINEERING_SCOPE_TERMS = {
    "robot",
    "robots",
    "robotics",
    "humanoid",
    "physical ai",
    "factory automation",
    "industrial automation",
    "automation system",
    "autonomous system",
    "robot cell",
    "warehouse automation",
    "construction automation",
    "drive-by-wire",
    "driverless",
    "mining truck",
    "haul truck",
    "heavy equipment",
    "off-road",
}
INTERESTING_ENGINEERING_OFF_SCOPE_TERMS = {
    "space",
    "orbit",
    "satellite",
    "military",
    "defense",
    "defence",
    "missile",
    "drone strike",
    "fighter jet",
    "quantum",
    "fusion",
    "battery breakthrough",
    "consumer gadget",
    "smartphone",
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


def is_industrial_robotics_product_launch_signal(item: StoredNormalizedItem) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return (
        has_any_term(haystack, ROBOTICS_TERMS)
        and has_any_term(haystack, INDUSTRIAL_ROBOTICS_PRODUCT_LAUNCH_TERMS)
        and has_any_term(haystack, INDUSTRIAL_ROBOTICS_PRODUCT_CONTEXT_TERMS)
    )

def is_obvious_off_scope(item: StoredNormalizedItem) -> bool:
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    if has_any_term(haystack, MILITARY_ROBOTICS_TERMS):
        return True
    if (
        has_any_term(haystack, CONSUMER_AV_SERVICE_TERMS)
        and has_any_term(haystack, CONSUMER_AV_GUIDE_TERMS)
        and not has_any_term(haystack, INDUSTRIAL_AUTONOMY_EXCEPTION_TERMS)
    ):
        return True
    if (
        (
            has_any_term(haystack, PHARMA_BIOTECH_PRODUCTION_TERMS)
            or (
                has_any_term(haystack, MEDICAL_CONTEXT_TERMS)
                and has_any_term(haystack, {"manufacturing", "production", "seed round", "funding", "raises", "raised"})
            )
            or (
                has_any_term(haystack, {"space", "orbit", "orbital", "in-space", "microgravity"})
                and has_any_term(haystack, PHARMA_BIOTECH_PRODUCTION_TERMS | MEDICAL_CONTEXT_TERMS)
            )
            or has_any_term(haystack, SPACE_BIOTECH_TERMS)
        )
        and not has_any_term(haystack, {"robot", "robots", "robotics", "factory automation", "construction automation"})
    ):
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
    if (
        has_any_term(haystack, {"timber", "mass timber", "clt", "glulam"})
        and has_any_term(haystack, TIMBER_LOGISTICS_OFF_SCOPE_TERMS)
        and not has_any_term(haystack, TIMBER_CONSTRUCTION_KEEP_TERMS)
    ):
        return True
    if (
        _source_extra(item, "strict_scope") == "industrial_robotics_physical_ai"
        and has_any_term(haystack, INTERESTING_ENGINEERING_OFF_SCOPE_TERMS)
        and not is_interesting_engineering_scope_signal(item)
    ):
        return True
    return False


def _source_tags(item: StoredNormalizedItem) -> set[str]:
    raw_tags = item.metadata.get("tags", [])
    return {str(tag).lower() for tag in raw_tags}


def _source_extra(item: StoredNormalizedItem, key: str) -> str | None:
    value = item.metadata.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def is_broad_feed_source(item: StoredNormalizedItem) -> bool:
    return bool(item.metadata.get("broad_feed"))


def is_housing_market_signal(item: StoredNormalizedItem) -> bool:
    market_scope = _source_extra(item, "market_scope")
    if market_scope not in {"germany_housing_market", "uk_housing_market"}:
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    terms = GERMANY_HOUSING_MARKET_TERMS if market_scope == "germany_housing_market" else UK_HOUSING_MARKET_TERMS
    return has_any_term(haystack, terms) and has_any_term(haystack, MARKET_SIGNAL_TERMS)


def is_construction_news_intelligence_signal(item: StoredNormalizedItem) -> bool:
    if item.source_id != "construction_news_intelligence_listing":
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return (
        has_any_term(haystack, UK_CONSTRUCTION_MARKET_TERMS)
        and (
            (has_any_term(haystack, MARKET_SIGNAL_TERMS) and has_any_term(haystack, UK_CONSTRUCTION_PRIORITY_TERMS))
            or has_any_term(haystack, UK_CONSTRUCTION_PROGRAMME_TERMS)
        )
        and not has_any_term(haystack, UK_CONSTRUCTION_OFF_SCOPE_SECTOR_TERMS)
    )


def is_business_insider_all3_signal(item: StoredNormalizedItem, event_flags: dict[str, bool]) -> bool:
    if item.source_id != "business_insider_feed":
        return True
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return any(
        (
            event_flags.get("industrial_robotics_signal", False),
            event_flags.get("construction_innovation_signal", False),
            event_flags.get("housing_market_signal", False),
            event_flags.get("timber_strategic_signal", False),
            event_flags.get("timber_policy_signal", False),
            event_flags.get("timber_economics_signal", False),
            event_flags.get("strategic_capability_acquisition_signal", False),
            event_flags.get("physical_industry_ai_megafunding_signal", False),
            event_flags.get("humanoid_affordability_signal", False),
        )
    ) or (
        has_any_term(
            haystack,
            {
                "robot",
                "robots",
                "robotics",
                "humanoid",
                "physical ai",
                "factory automation",
                "industrial automation",
                "construction",
                "housing",
                "timber",
                "mass timber",
                "prefab",
                "prefabrication",
                "modular",
            },
        )
        and any(
            (
                event_flags.get("funding_event", False),
                event_flags.get("partnership_event", False),
                event_flags.get("acquisition_event", False),
                event_flags.get("deployment_event", False),
                event_flags.get("product_launch_event", False),
                event_flags.get("quantified_scale_signal", False),
            )
        )
    )


def is_construction_briefing_scope_signal(item: StoredNormalizedItem) -> bool:
    if _source_extra(item, "strict_scope") != "construction_timber_innovation":
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return has_any_term(haystack, CONSTRUCTION_BRIEFING_SCOPE_TERMS)


def is_interesting_engineering_scope_signal(item: StoredNormalizedItem) -> bool:
    if _source_extra(item, "strict_scope") != "industrial_robotics_physical_ai":
        return False
    haystack = _normalize_text(f"{item.title} {item.text_preview or ''}")
    return has_any_term(haystack, INTERESTING_ENGINEERING_SCOPE_TERMS)


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
    source_tags = _source_tags(item)
    if competitor_count > 0:
        return True
    if event_flags.get("strategic_ai_major_deal_signal"):
        return True
    if event_flags.get("strategic_capability_acquisition_signal"):
        return True
    if event_flags.get("physical_industry_ai_megafunding_signal"):
        return True
    if event_flags.get("construction_statistics_signal"):
        return True
    if event_flags.get("construction_news_intelligence_signal"):
        return True
    if event_flags.get("housing_market_signal"):
        return True
    if event_flags.get("timber_policy_signal"):
        return True
    if event_flags.get("timber_economics_signal"):
        return True
    if event_flags.get("robotic_timber_fabrication_signal"):
        return True
    if event_flags.get("adaptive_reuse_housing_delivery_signal"):
        return True
    if event_flags.get("national_robotics_strategy_signal"):
        return True
    if event_flags.get("robot_safety_governance_signal"):
        return True
    if is_construction_briefing_scope_signal(item):
        return True
    if is_interesting_engineering_scope_signal(item):
        return True
    if has_any_term(haystack, BROAD_FEED_SCOPE_TERMS):
        return True
    if event_flags.get("timber_strategic_signal"):
        return True
    if has_any_term(haystack, ROBOTICS_BUSINESS_ENTITY_TERMS) and has_any_term(
        haystack, ROBOTICS_BUSINESS_PERFORMANCE_TERMS
    ):
        return True
    if is_industrial_robotics_product_launch_signal(item):
        return True
    if has_any_term(haystack, ROBOTICS_TERMS) and has_any_term(haystack, STRATEGIC_WORK_ENV_TERMS):
        return True
    if has_any_term(haystack, ROBOTICS_TERMS) and has_any_term(haystack, INDUSTRIAL_ROBOTICS_CONTEXT_TERMS):
        return True
    if (
        event_flags.get("funding_event")
        and event_flags.get("quantified_scale_signal")
        and has_any_term(haystack, ROBOTICS_TERMS)
        and bool(source_tags & {"robotics", "robot", "humanoid", "industrial"})
    ):
        return True
    if event_flags.get("factory_opening_or_expansion") and (
        has_any_term(haystack, ROBOTICS_TERMS)
        or bool(source_tags & {"robotics", "robot", "humanoid", "industrial"})
        or has_any_term(haystack, ROBOTICS_FACTORY_SIGNAL_TERMS)
    ):
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
    if not is_business_insider_all3_signal(item, event_flags):
        return "drop", "no_clear_all3_scope"
    if is_broad_feed_source(item):
        haystack = f"{item.title} {item.text_preview or ''}"
        source_tags = _source_tags(item)
        high_intent_scope = has_any_term(haystack, HIGH_INTENT_BROAD_FEED_TERMS)
        strong_broad_signal = (
            competitor_count > 0
            or event_flags.get("housing_market_signal")
            or event_flags.get("strategic_ai_major_deal_signal")
            or event_flags.get("strategic_capability_acquisition_signal")
            or event_flags.get("physical_industry_ai_megafunding_signal")
            or event_flags.get("national_robotics_strategy_signal")
            or event_flags.get("robot_safety_governance_signal")
            or is_construction_briefing_scope_signal(item)
            or is_interesting_engineering_scope_signal(item)
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
                event_flags.get("funding_event")
                and event_flags.get("quantified_scale_signal")
                and has_any_term(haystack, ROBOTICS_TERMS)
                and bool(source_tags & {"robotics", "robot", "humanoid", "industrial"})
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
