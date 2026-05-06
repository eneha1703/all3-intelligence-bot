from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import StoredNormalizedItem
from all3_radar.pipeline.ranking import derive_event_flags, rank_item


def _make_item(title: str, preview: str, broad_feed: bool, source_id: str = "source-1") -> StoredNormalizedItem:
    now = datetime.now(timezone.utc)
    return StoredNormalizedItem(
        normalized_item_id="item-1",
        raw_item_id="raw-1",
        source_id=source_id,
        canonical_url="https://example.com/story",
        domain="example.com",
        title=title,
        text_preview=preview,
        published_ts=now,
        collected_ts=now,
        layer=SourceLayer.DIRECT,
        is_wrapper=False,
        directness_rank=100,
        metadata={"tags": ["robotics"], "broad_feed": broad_feed},
    )


RANKING_RULES = {
    "signals": {
        "competitor_mention": 35,
        "direct_source": 25,
        "official_statistics_source": 8,
        "direct_wood_central_source": 8,
        "google_competitor_wrapper": -30,
        "funding_event": 18,
        "partnership_event": 16,
        "acquisition_event": 20,
        "deployment_event": 20,
        "factory_opening_or_expansion": 18,
        "permitting_or_code_signal": 18,
        "quantified_scale_signal": 15,
        "timber_strategic_signal": 15,
        "timber_performance_signal": 12,
        "industrial_robotics_signal": 8,
        "robotic_timber_fabrication_signal": 14,
        "adaptive_reuse_housing_delivery_signal": 22,
        "national_robotics_strategy_signal": 16,
        "robot_safety_governance_signal": 12,
        "humanoid_affordability_signal": 8,
        "strategic_capability_acquisition_signal": 12,
        "construction_innovation_signal": 6,
        "construction_statistics_signal": 18,
        "housing_market_signal": 12,
        "construction_news_intelligence_signal": 12,
        "construction_briefing_scope_signal": 6,
        "interesting_engineering_scope_signal": 6,
        "timber_policy_signal": 18,
        "timber_economics_signal": 18,
        "consumer_robotics_penalty": -50,
        "showcase_only_architecture_penalty": -20,
    },
    "thresholds": {
        "store_min_score": 0,
        "shortlist_min_score": 20,
        "send_min_score": 28,
    },
}


def test_industrial_physical_ai_story_reaches_send_threshold() -> None:
    item = _make_item(
        "Neura Robotics and Dassault Systèmes partner to scale physical AI",
        "The agreement links robot training in virtual twins with real-world deployment in physical robot environments.",
        broad_feed=True,
    )

    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert decision.relevance_status == "keep"
    assert decision.score >= 28


def test_modular_quantified_construction_story_reaches_send_threshold() -> None:
    item = _make_item(
        "Messer Construction breaks ground on $280M university health building",
        "The 257,000-square-foot facility will feature modular teaching spaces for multiple professions.",
        broad_feed=False,
    )

    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert decision.relevance_status == "keep"
    assert decision.score >= 28


def test_humanoid_factory_opening_sets_factory_signal_and_stays_in_scope() -> None:
    item = _make_item(
        "1X Opens NEO Factory in Hayward, CA",
        "Spanning 58,000 square feet the NEO Factory features fully vertically integrated hardware manufacturing and production lines.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"tags": ["robotics", "humanoid", "industrial"], "broad_feed": False}})

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["factory_opening_or_expansion"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 58


def test_destatis_statistics_story_now_survives() -> None:
    item = _make_item(
        "Auftragseingang im Bauhauptgewerbe im Februar 2026: +7,3 % zum Vormonat",
        "Der reale Auftragseingang im Bauhauptgewerbe ist im Februar 2026 gegenüber Januar 2026 gestiegen.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "destatis_press_listing"})

    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert decision.relevance_status == "keep"
    assert decision.send_status == "stored_only"
    assert decision.score == 51


def test_telegraph_housing_market_story_gets_market_signal_and_score_lift() -> None:
    item = _make_item(
        "UK housing shortage deepens as completions fall and rents rise",
        "A new housing market report says completions fell 14% while rents rose across the UK residential market.",
        broad_feed=True,
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "telegraph_feed",
            "metadata": {"tags": ["news"], "broad_feed": True, "market_scope": "uk_housing_market"},
        }
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["housing_market_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score == 37


def test_interesting_engineering_robotics_story_gets_scope_signal() -> None:
    item = _make_item(
        "Humanoid robot platform expands industrial automation deployments",
        "The company says the robotics system will scale physical AI and factory automation workflows across manufacturing sites.",
        broad_feed=True,
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "interesting_engineering_rss",
            "metadata": {
                "tags": ["engineering"],
                "broad_feed": True,
                "strict_scope": "industrial_robotics_physical_ai",
            },
        }
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["interesting_engineering_scope_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 39


def test_aeon_partnership_story_sets_partnership_event() -> None:
    item = _make_item(
        "AEON humanoid robot partnered with Fill to automate factory operations",
        "The companies partnered to deploy humanoid robots for real-world autonomy across manufacturing operations.",
        broad_feed=True,
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "interesting_engineering_rss",
            "metadata": {
                "tags": ["engineering"],
                "broad_feed": True,
                "strict_scope": "industrial_robotics_physical_ai",
            },
        }
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["partnership_event"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 55


def test_heavy_autonomy_story_gets_industrial_robotics_signal() -> None:
    item = _make_item(
        "China unveils driverless mining truck with drive-by-wire corner modules",
        "The 110 ton mining truck uses drive-by-wire corner modules for driverless off-road heavy equipment operations.",
        broad_feed=True,
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "interesting_engineering_rss",
            "metadata": {
                "tags": ["engineering"],
                "broad_feed": True,
                "strict_scope": "industrial_robotics_physical_ai",
            },
        }
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["interesting_engineering_scope_signal"] is True
    assert flags["industrial_robotics_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 39


def test_construction_news_market_story_gets_market_signal_and_score_lift() -> None:
    item = _make_item(
        "UK construction activity falls as infrastructure starts weaken",
        "A new report says construction activity, project starts and main contract awards fell across infrastructure and commercial work.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "construction_news_intelligence_listing",
            "metadata": {"tags": ["construction", "uk", "market"], "market_scope": "uk_construction_market"},
        }
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["construction_news_intelligence_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 37


def test_unitree_humanoid_affordability_story_gets_access_signal_and_score_lift() -> None:
    item = _make_item(
        "China’s Unitree reshapes entry-level humanoid robot market with $4,290 droid",
        "Unitree has begun selling humanoid robots globally through AliExpress, with its R1 model listed at $4,290 and positioned far below many western peers.",
        broad_feed=True,
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "interesting_engineering_rss",
            "metadata": {
                "tags": ["engineering"],
                "broad_feed": True,
                "strict_scope": "industrial_robotics_physical_ai",
            },
        }
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["interesting_engineering_scope_signal"] is True
    assert flags["humanoid_affordability_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score == 39


def test_wood_central_timber_policy_story_now_survives_without_funding_flag() -> None:
    item = _make_item(
        "Architects, insurers open new front on English timber cap",
        "Architects and insurers have raised fresh concerns over England's timber height cap as pressure grows around standards, approvals and insurance treatment.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "wood_central_api"})

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["funding_event"] is False
    assert flags["timber_policy_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.send_status == "stored_only"
    assert decision.score == 51


def test_wood_central_timber_economics_story_now_survives() -> None:
    item = _make_item(
        "Mass timber premiums run six to ten times higher than concrete and steel",
        "A quantified cost comparison suggests mass timber premiums remain a major adoption barrier for commercial viability and timber scaling.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "wood_central_api"})

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["timber_economics_signal"] is True
    assert flags["timber_strategic_signal"] is True
    assert flags["timber_performance_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.send_status == "stored_only"
    assert decision.score == 78


def test_wood_central_timber_performance_story_gets_signal_and_score_lift() -> None:
    item = _make_item(
        "Concrete Loses 32% More Heat Than Mass Timber in Chile's Cold Zones",
        "Concrete buildings lose between 26 and 32 per cent more heat than mass timber buildings of identical typology when thermal bridges are included in the calculation.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "wood_central_api"})

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["timber_performance_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score == 45


def test_major_industrial_ai_funding_story_from_broad_feed_reaches_send_path() -> None:
    item = _make_item(
        "Project Prometheus raises funding at $38B valuation for physics AI",
        "The company says the round will expand AI systems for engineering, manufacturing and production workflows across physical industries.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["strategic_ai_major_deal_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.send_status == "stored_only"
    assert decision.score == 43


def test_physical_industry_ai_megafunding_story_survives_scope_gate() -> None:
    item = _make_item(
        "After a $10B raise, a new AI startup becomes one of the most valuable five-month-old startups ever funded",
        "The company says the round will expand aerospace, automotive, advanced manufacturing, engineering workflows, and robotics capabilities across physical industries.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["physical_industry_ai_megafunding_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.skip_reason is None


def test_generic_megafunding_ai_story_without_physical_terms_remains_out_of_scope() -> None:
    item = _make_item(
        "After a $10B raise, an AI startup becomes one of the most valuable five-month-old startups ever funded",
        "The company says the round will expand enterprise AI assistants, customer support automation, and office productivity tools.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["physical_industry_ai_megafunding_signal"] is False
    assert decision.relevance_status == "drop"
    assert decision.skip_reason == "no_clear_all3_scope"


def test_ai_coding_assistant_funding_remains_out_of_scope() -> None:
    item = _make_item(
        "AI coding assistant startup raises $2B to expand developer tooling",
        "The company said the funding will expand code completion, agent workflows, and office productivity integrations.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["physical_industry_ai_megafunding_signal"] is False
    assert decision.relevance_status == "drop"
    assert decision.skip_reason == "no_clear_all3_scope"


def test_robotics_manufacturing_ai_funding_remains_in_scope() -> None:
    item = _make_item(
        "Industrial AI startup raises $1.2B to expand robotics and manufacturing software",
        "The company says the funding will support factory deployment, robotics systems, and manufacturing workflow automation.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["physical_industry_ai_megafunding_signal"] is True
    assert decision.relevance_status == "keep"


def test_smaller_generic_ai_funding_remains_out_of_scope() -> None:
    item = _make_item(
        "Enterprise AI startup raises $45M to scale workflow assistants",
        "The funding will help the company expand customer support, productivity, and internal knowledge tools.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["physical_industry_ai_megafunding_signal"] is False
    assert decision.relevance_status == "drop"
    assert decision.skip_reason == "no_clear_all3_scope"


def test_weaker_physical_wording_requires_billion_scale() -> None:
    large_item = _make_item(
        "AI startup raises $3B to expand engineering and automation platforms",
        "The company says the funding will support engineering and automation systems used across the physical world.",
        broad_feed=True,
    )
    small_item = _make_item(
        "AI startup raises $80M to expand engineering and automation platforms",
        "The company says the funding will support engineering and automation systems used across the physical world.",
        broad_feed=True,
    )

    large_flags = derive_event_flags(large_item)
    small_flags = derive_event_flags(small_item)

    assert large_flags["physical_industry_ai_megafunding_signal"] is True
    assert small_flags["physical_industry_ai_megafunding_signal"] is False


def test_major_industrial_ai_merger_story_from_broad_feed_reaches_send_path() -> None:
    item = _make_item(
        "Cohere and Aleph Alpha explore merger with Schwarz Group backing",
        "The proposed $20B merger with $600M backing would combine enterprise AI with engineering, industrial automation and manufacturing workflow software for European production environments.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["strategic_ai_major_deal_signal"] is True
    assert flags["acquisition_event"] is True
    assert decision.relevance_status == "keep"
    assert decision.send_status == "stored_only"
    assert decision.score >= 60


def test_meta_humanoid_robotics_acquisition_story_gets_strategic_capability_signal() -> None:
    item = _make_item(
        "Meta buys robotics startup to bolster its humanoid AI ambitions",
        "The deal adds robotics talent and technology to Meta's humanoid AI push.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["acquisition_event"] is True
    assert flags["strategic_capability_acquisition_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score == 57


def test_construction_company_robotics_acquisition_story_gets_strategic_capability_signal() -> None:
    item = _make_item(
        "Builder buys construction robotics startup to speed modular housing delivery",
        "The acquisition gives the construction company robotics and prefab automation capability for jobsite and factory workflows.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["acquisition_event"] is True
    assert flags["strategic_capability_acquisition_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 57


def test_abb_like_launch_sets_product_launch_event() -> None:
    item = _make_item(
        "ABB Robotics launches PoWa cobot family targeting industrial tasks",
        "ABB Robotics said its new PoWa family of cobots addresses a long-standing gap in the market between traditional cobots.",
        broad_feed=False,
    )

    flags = derive_event_flags(item)

    assert flags["product_launch_event"] is True


def test_ency_like_platform_update_sets_product_launch_event() -> None:
    item = _make_item(
        "Ency updates hybrid robot programming platform with multi-brand and 3D vision capabilities",
        "Ency Software has released a major update to its Ency Hyper platform, adding support for mixed-brand robot cells, SCARA robots, and integrated 3D vision on physical robots.",
        broad_feed=False,
    )

    flags = derive_event_flags(item)

    assert flags["product_launch_event"] is True


def test_kollmorgen_like_tool_launch_sets_product_launch_event() -> None:
    item = _make_item(
        "Kollmorgen launches layout analysis tool to improve mobile robot performance",
        "Kollmorgen has introduced a new software tool called the NDC Layout Assistant to improve routes for automated guided vehicles and autonomous mobile robots.",
        broad_feed=False,
    )

    flags = derive_event_flags(item)

    assert flags["product_launch_event"] is True


def test_generic_thought_leadership_does_not_set_product_launch_event() -> None:
    item = _make_item(
        "Why industrial AI platforms matter for the next decade",
        "A commentary on how manufacturers should think about software strategy and long-term adoption choices.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)

    assert flags["product_launch_event"] is False


def test_generic_ai_business_profile_does_not_set_product_launch_event() -> None:
    item = _make_item(
        "AI startup expands enterprise platform ambitions in Europe",
        "The company profile outlines hiring plans, go-to-market strategy, and customer traction without a concrete product launch.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)

    assert flags["product_launch_event"] is False


def test_funding_only_story_does_not_set_product_launch_event() -> None:
    item = _make_item(
        "Construction robotics startup raises $25M seed round",
        "The funding will help the company scale hiring and expand internationally.",
        broad_feed=False,
    )

    flags = derive_event_flags(item)

    assert flags["funding_event"] is True
    assert flags["product_launch_event"] is False


def test_wood_central_robotic_mass_timber_fabrication_reaches_send_threshold() -> None:
    item = _make_item(
        "Toronto Robot Mills Mass Timber to within 0.06-Millimetre Precision",
        "Toronto researchers are milling mass timber components with a 3.5-metre KUKA robotic arm for construction.",
        broad_feed=False,
        source_id="wood_central_api",
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["robotic_timber_fabrication_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 28


def test_wood_central_fast_olympic_village_conversion_is_not_showcase_noise() -> None:
    item = _make_item(
        "Milan's Olympic Village to Reopen to Students in Just Four Months",
        "The mass timber Olympic Village is converting from athletes' accommodation into student housing in a four-month works programme.",
        broad_feed=False,
        source_id="wood_central_api",
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["adaptive_reuse_housing_delivery_signal"] is True
    assert flags["showcase_only_architecture_penalty"] is False
    assert decision.relevance_status == "keep"
    assert decision.score >= 28


def test_broad_feed_national_robotics_strategy_is_strong_scope() -> None:
    item = _make_item(
        "IFR Reports China Making AI-Powered Robots Core of National Strategy",
        "China's 15th Five-Year Plan places robotics at the heart of its industrial system and pushes AI research toward physical applications.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["national_robotics_strategy_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 28


def test_robot_rulebook_safety_research_has_narrow_governance_scope() -> None:
    item = _make_item(
        "Researchers Say Autonomous Robots Can Make Safer Decisions With Rulebooks System",
        "The rulebooks framework helps autonomous robots make transparent decisions when rules conflict in real-world situations.",
        broad_feed=True,
    )

    flags = derive_event_flags(item)
    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert flags["robot_safety_governance_signal"] is True
    assert decision.relevance_status == "keep"
    assert decision.score >= 28
