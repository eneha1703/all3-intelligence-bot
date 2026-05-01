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
