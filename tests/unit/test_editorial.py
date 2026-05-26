from datetime import datetime, timezone

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem
from all3_radar.domain.enums import SourceLayer
from all3_radar.pipeline.editorial import evaluate_send_stage_editorial


def _make_item(title: str, preview: str, source_id: str = "source-1") -> StoredNormalizedItem:
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
        metadata={},
    )


def _make_decision(**event_flags: bool) -> RankedDecision:
    return RankedDecision(
        relevance_status="keep",
        send_status="stored_only",
        skip_reason=None,
        score=40,
        signals={"competitor_count": 0, "event_flags": event_flags},
        is_shortlisted=True,
        is_borderline=False,
    )


def test_editorial_shaping_rejects_thought_leadership_without_operational_signal() -> None:
    item = _make_item(
        "From sci-fi to reality: Physical AI’s future with Dr. Jan Liphardt",
        "Dr. Jan Liphardt discusses the future of robotics and safety in human-robot interactions.",
    )
    decision = _make_decision()

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_thought_leadership_without_operational_signal"


def test_editorial_shaping_keeps_operational_product_launch() -> None:
    item = _make_item(
        "Ency updates hybrid robot programming platform with multi-brand and 3D vision capabilities",
        "The update adds support for mixed-brand robot cells, SCARA robots, and integrated 3D vision on physical robots.",
    )
    decision = _make_decision(industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None


def test_editorial_shaping_rejects_adjacent_logistics_without_all3_signal() -> None:
    item = _make_item(
        "Warehouse robotics pilot expands in logistics hubs",
        "The deployment adds AMR routes across warehouse operations and material handling sites.",
    )
    decision = _make_decision(deployment_event=True, adjacent_logistics_only=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_adjacent_logistics_without_all3_signal"


def test_editorial_shaping_rejects_military_robotics() -> None:
    item = _make_item(
        "Defense startup deploys battlefield robots for frontline missions",
        "The military robotics platform will support combat operations and defense logistics on the battlefield.",
    )
    decision = _make_decision(deployment_event=True, industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_military_or_combat_out_of_scope"


def test_editorial_shaping_rejects_business_profile_noise() -> None:
    item = _make_item(
        "Billionaire banker lists luxury estate while seeking private AI shares",
        "The banker is marketing a luxury estate as part of a personal wealth trade tied to private-company shares.",
    )
    decision = _make_decision()

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_business_profile_out_of_scope"


def test_editorial_shaping_keeps_destatis_construction_market_signal() -> None:
    item = _make_item(
        "Auftragseingang im Bauhauptgewerbe im Februar 2026: +7,3 % zum Vormonat",
        "Der reale Auftragseingang im Bauhauptgewerbe ist im Februar 2026 gegenuber Januar 2026 gestiegen.",
        source_id="destatis_press_listing",
    )
    decision = _make_decision(construction_statistics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["official_construction_market_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_uk_housing_market_signal() -> None:
    item = _make_item(
        "UK housing shortage deepens as completions fall and rents rise",
        "A new housing market report says completions fell 14% while rents rose across the UK residential market.",
        source_id="telegraph_feed",
    )
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"market_scope": "uk_housing_market", "broad_feed": True}})
    decision = _make_decision(housing_market_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["housing_market_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_haufe_completion_and_permit_timing_story() -> None:
    item = _make_item(
        "Wohnungsbau-Statistik: Negativrekord bei Fertigstellungen",
        (
            "Statistisches Bundesamt: 2025 wurden so wenig neue Wohnungen fertiggestellt wie seit 2012 nicht. "
            "Nach Angaben von Colliers dauert es inzwischen mehr als zwei Jahre von der Genehmigung bis zur Fertigstellung."
        ),
        source_id="haufe_immobilien_listing",
    )
    item = StoredNormalizedItem(
        **{**item.__dict__, "metadata": {"market_scope": "germany_housing_market", "broad_feed": True}}
    )
    decision = _make_decision(housing_market_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["housing_market_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_uk_construction_market_signal() -> None:
    item = _make_item(
        "UK construction activity falls as infrastructure starts weaken",
        "A new report says construction activity, project starts and main contract awards fell across infrastructure and commercial work.",
        source_id="construction_news_intelligence_listing",
    )
    item = StoredNormalizedItem(
        **{**item.__dict__, "metadata": {"market_scope": "uk_construction_market", "broad_feed": False}}
    )
    decision = _make_decision(construction_news_intelligence_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["uk_construction_market_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_destatis_housing_overcrowding_signal() -> None:
    item = _make_item(
        "11,7 % der Bevölkerung in Deutschland lebten 2025 in überbelegten Wohnungen",
        "Neue Destatis-Zahlen zeigen, dass 11,7 % der Bevölkerung in Deutschland in überbelegten Wohnungen lebten.",
        source_id="destatis_press_listing",
    )
    item = StoredNormalizedItem(
        **{**item.__dict__, "metadata": {"market_scope": "germany_housing_market", "origin_language": "de"}}
    )
    decision = _make_decision(housing_market_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["housing_market_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_haufe_germany_housing_policy_signal() -> None:
    item = _make_item(
        "Berlin: Senat beschliesst Gesetz fuer einfaches Bauen",
        "Die Koalition will mit einem Gesetz fuer einfaches Bauen den Wohnungsbau beschleunigen und Wohnungsnot angehen.",
        source_id="haufe_immobilien_listing",
    )
    item = StoredNormalizedItem(
        **{**item.__dict__, "metadata": {"market_scope": "germany_housing_market", "origin_language": "de"}}
    )
    decision = _make_decision(housing_market_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["housing_market_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_humanoid_affordability_market_signal() -> None:
    item = _make_item(
        "China’s Unitree reshapes entry-level humanoid robot market with USD 4,290 droid",
        "Unitree has begun selling humanoid robots globally through AliExpress, with its R1 model listed at USD 4,290 and positioned far below many western peers.",
        source_id="interesting_engineering_rss",
    )
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True, "strict_scope": "industrial_robotics_physical_ai"}})
    decision = _make_decision(humanoid_affordability_signal=True, interesting_engineering_scope_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["humanoid_access_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_robot_ai_training_infrastructure_story() -> None:
    item = _make_item(
        "Tutor Intelligence builds Data Factory to train robot AI in the real world",
        "Tutor Intelligence is running 100 Sonny semi-humanoid robots while sharing real-world data with its mobile manipulator platform.",
        source_id="robot_report_rss",
    )
    decision = _make_decision(industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["robot_ai_training_infrastructure_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_heavy_industrial_autonomy_story() -> None:
    item = _make_item(
        "China unveils driverless mining truck with drive-by-wire corner modules",
        "The 110 ton mining truck uses drive-by-wire corner modules for driverless off-road heavy equipment operations.",
        source_id="interesting_engineering_rss",
    )
    item = StoredNormalizedItem(
        **{**item.__dict__, "metadata": {"broad_feed": True, "strict_scope": "industrial_robotics_physical_ai"}}
    )
    decision = _make_decision(
        industrial_robotics_signal=True,
        interesting_engineering_scope_signal=True,
        quantified_scale_signal=True,
    )

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["heavy_industrial_autonomy_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_sustained_factory_operation_story() -> None:
    item = _make_item(
        "Helix-02 robots now sustain full factory-style 8-hour shifts without intervention",
        "Figure says the humanoid robots can sustain full factory-style 8-hour shifts without intervention across manufacturing tasks.",
        source_id="interesting_engineering_rss",
    )
    item = StoredNormalizedItem(
        **{**item.__dict__, "metadata": {"broad_feed": True, "strict_scope": "industrial_robotics_physical_ai"}}
    )
    decision = _make_decision(industrial_robotics_signal=True, interesting_engineering_scope_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["sustained_factory_operation_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_short_humanoid_affordability_preview() -> None:
    item = _make_item(
        "China's Unitree reshapes entry-level humanoid robot market with $4,290 droid",
        "Chinese robotics firm Unitree has introduced a low-cost bipedal humanoid robot with an upper-body-only design.",
        source_id="interesting_engineering_rss",
    )
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True, "strict_scope": "industrial_robotics_physical_ai"}})
    decision = _make_decision(humanoid_affordability_signal=True, interesting_engineering_scope_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["humanoid_access_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_wood_central_timber_barrier_signal() -> None:
    item = _make_item(
        "Architects, insurers open new front on English timber cap",
        "Architects and insurers have raised fresh concerns over England's timber height cap as pressure grows around standards, approvals and insurance treatment.",
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_policy_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["timber_adoption_barrier_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_wood_central_timber_economics_signal() -> None:
    item = _make_item(
        "Mass timber premiums run six to ten times higher than concrete and steel",
        "A quantified cost comparison suggests mass timber premiums remain a major adoption barrier for commercial viability and timber scaling.",
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_economics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["timber_economics_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_wood_central_timber_performance_signal() -> None:
    item = _make_item(
        "Concrete Loses 32% More Heat Than Mass Timber in Chile's Cold Zones",
        "Concrete buildings lose between 26 and 32 per cent more heat than mass timber buildings of identical typology when thermal bridges are included in the calculation.",
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_performance_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["timber_performance_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_wood_central_timber_project_delivery_signal() -> None:
    item = _make_item(
        "22-Storey Mass Timber Pod Hotel Targets Vancouver's Howe Street",
        "The 408-unit project has entered Vancouver's rezoning process through a formal application.",
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_policy_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["timber_project_delivery_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_wood_central_timber_strategic_shift_signal() -> None:
    item = _make_item(
        "Mass Timber Could Gain New Ground as Architects Turn From Glass",
        (
            "Architects are moving away from glass curtain walling as climate urgency and embodied carbon "
            "concerns push demand toward brick, concrete and engineered timber in more durable buildings."
        ),
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_strategic_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["timber_strategic_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_macro_statistics_without_construction_signal_blocked() -> None:
    item = _make_item(
        "Consumer prices in Germany rise 0.2% in April 2026",
        "Official figures show a monthly increase in consumer prices across the broader economy.",
        source_id="destatis_press_listing",
    )
    decision = _make_decision()

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_not_telegram_worthy"
    assert editorial.flags["official_construction_market_signal"] is False


def test_editorial_shaping_keeps_soft_wood_central_commentary_blocked() -> None:
    item = _make_item(
        "Why timber policy needs a broader conversation",
        "A commentary on how the industry should think about long-term timber standards and policy direction.",
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_policy_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_thought_leadership_without_operational_signal"
    assert editorial.flags["timber_adoption_barrier_signal"] is False
    assert editorial.flags["timber_economics_alert_signal"] is False


def test_editorial_shaping_keeps_soft_wood_central_economics_commentary_blocked() -> None:
    item = _make_item(
        "Why mass timber economics deserve a broader conversation",
        "A commentary on long-term timber costs and market positioning without a quantified comparison or a concrete adoption barrier.",
        source_id="wood_central_api",
    )
    decision = _make_decision(timber_economics_signal=False)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_thought_leadership_without_operational_signal"
    assert editorial.flags["timber_economics_alert_signal"] is False


def test_editorial_shaping_keeps_strong_strategic_industrial_ai_funding_story() -> None:
    item = _make_item(
        "Project Prometheus raises funding at $38B valuation for physics AI",
        "The company says the round will expand AI systems for engineering, manufacturing and production workflows across physical industries.",
        source_id="tech_funding_news_rss",
    )
    decision = _make_decision(strategic_ai_major_deal_signal=True, funding_event=True)
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True}})

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["strategic_industrial_ai_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_strategic_robotics_capability_acquisition() -> None:
    item = _make_item(
        "Meta buys robotics startup to bolster its humanoid AI ambitions",
        "The deal adds robotics talent and technology to Meta's humanoid AI push.",
        source_id="techcrunch_rss",
    )
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True}})
    decision = _make_decision(acquisition_event=True, strategic_capability_acquisition_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["strategic_capability_acquisition_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_construction_robotics_capability_acquisition() -> None:
    item = _make_item(
        "Builder buys construction robotics startup to speed modular housing delivery",
        "The acquisition gives the construction company robotics and prefab automation capability for jobsite and factory workflows.",
        source_id="techcrunch_rss",
    )
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True}})
    decision = _make_decision(acquisition_event=True, strategic_capability_acquisition_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["strategic_capability_acquisition_alert_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_strategic_ai_merger_stored_only_without_stronger_real_world_signal() -> None:
    item = _make_item(
        "Cohere and Aleph Alpha explore merger with Schwarz Group backing",
        "The proposed $20B merger with $600M backing would combine enterprise AI with engineering, industrial automation and manufacturing workflow software for European production environments.",
        source_id="tech_funding_news_rss",
    )
    decision = _make_decision(strategic_ai_major_deal_signal=True, acquisition_event=True)
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True}})

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_strategic_ai_deal_stored_only"
    assert editorial.flags["strategic_industrial_ai_alert_signal"] is False


def test_editorial_shaping_keeps_generic_ai_finance_blocked() -> None:
    item = _make_item(
        "Google to invest up to $40B in Anthropic in cash and compute",
        "A major AI financing story focused on model scaling, compute access and corporate strategy for foundation models and cloud infrastructure.",
        source_id="tech_funding_news_rss",
    )
    decision = _make_decision(funding_event=True)
    item = StoredNormalizedItem(**{**item.__dict__, "metadata": {"broad_feed": True}})

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_not_telegram_worthy"
    assert editorial.flags["strategic_industrial_ai_alert_signal"] is False


def test_editorial_shaping_keeps_robotic_timber_fabrication_story() -> None:
    item = _make_item(
        "Toronto Robot Mills Mass Timber to within 0.06-Millimetre Precision",
        "Toronto researchers are milling mass timber components with a 3.5-metre KUKA robotic arm for construction.",
        source_id="wood_central_api",
    )
    decision = _make_decision(robotic_timber_fabrication_signal=True, industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.flags["robotic_timber_fabrication_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_fast_student_housing_conversion_story() -> None:
    item = _make_item(
        "Milan's Olympic Village to Reopen to Students in Just Four Months",
        "The mass timber Olympic Village is converting from athletes' accommodation into student housing in a four-month works programme.",
        source_id="wood_central_api",
    )
    decision = _make_decision(adaptive_reuse_housing_delivery_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.flags["adaptive_reuse_housing_delivery_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_national_robotics_strategy_story() -> None:
    item = _make_item(
        "IFR Reports China Making AI-Powered Robots Core of National Strategy",
        "China's 15th Five-Year Plan places robotics at the heart of its industrial system and pushes AI research toward physical applications.",
        source_id="ai_insider_rss",
    )
    decision = _make_decision(national_robotics_strategy_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.flags["national_robotics_strategy_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_robot_rulebook_safety_story() -> None:
    item = _make_item(
        "Researchers Say Autonomous Robots Can Make Safer Decisions With Rulebooks System",
        "The rulebooks framework helps autonomous robots make transparent decisions when rules conflict in real-world situations.",
        source_id="ai_insider_rss",
    )
    decision = _make_decision(robot_safety_governance_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.flags["robot_safety_governance_signal"] is True
    assert editorial.flags["telegram_worthy"] is True


def test_editorial_shaping_keeps_industrial_automation_partnership_story() -> None:
    item = _make_item(
        "Comau and Aptiv partner on AI-powered robotics and autonomous industrial automation systems",
        "The partnership combines AI-powered robotics with autonomous industrial automation systems for manufacturing and factory production environments.",
        source_id="robotics_automation_news_rss",
    )
    decision = _make_decision(partnership_event=True, industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None
    assert editorial.flags["industrial_automation_partnership_signal"] is True
    assert editorial.flags["telegram_worthy"] is True
