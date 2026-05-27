from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import RankedDecision, SourceDefinition, StoredNormalizedItem
from all3_radar.pipeline.radar_service import (
    CurrentRunContext,
    _is_allowed_medium_claude_editorial_promotion,
    _should_fallback_after_claude_final_card_rejection,
    _should_fallback_to_protected_market_signal_after_final_card_invalid_output,
    _should_fallback_to_editorial_promotion_after_final_card_invalid_output,
    _should_drop_after_claude_final_card_error,
    _should_protect_from_high_confidence_claude_editorial_rejection,
    _should_skip_claude_final_card,
)
from all3_radar.summarization.claude_editorial_review_client import ClaudeEditorialReviewResult


def _make_context(
    *,
    title: str,
    preview: str,
    source_id: str,
    metadata: dict,
    event_flags: dict,
    editorial_flags: dict | None = None,
    score: int = 52,
) -> CurrentRunContext:
    now = datetime.now(timezone.utc)
    item = StoredNormalizedItem(
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
        metadata=metadata,
    )
    decision = RankedDecision(
        relevance_status="keep",
        send_status="stored_only",
        skip_reason=None,
        score=score,
        signals={
            "competitor_count": 0,
            "event_flags": event_flags,
            "editorial_flags": editorial_flags or {},
        },
        is_shortlisted=True,
        is_borderline=False,
    )
    source = SourceDefinition(
        id=source_id,
        name="Test Source",
        kind=SourceKind.RSS,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="generic_rss",
        url="https://example.com/feed.xml",
        priority=100,
        tags=("test",),
    )
    return CurrentRunContext(
        source=source,
        item=item,
        freshness=None,
        decision=decision,
    )


def test_medium_claude_editorial_promotion_is_allowed_for_destatis_housing_market_story() -> None:
    context = _make_context(
        title="11,7 % der Bevölkerung in Deutschland lebten 2025 in überbelegten Wohnungen",
        preview="Neue Destatis-Zahlen zeigen, dass 11,7 % der Bevölkerung in Deutschland in überbelegten Wohnungen lebten.",
        source_id="destatis_press_listing",
        metadata={"market_scope": "germany_housing_market", "origin_language": "de"},
        event_flags={"housing_market_signal": True},
        score=63,
    )
    result = ClaudeEditorialReviewResult(
        send_ok=True,
        reject_reason=None,
        edited_title="Overcrowded housing still affects 11.7% of Germany's population",
        edited_summary="Official Destatis figures show 11.7% of Germany's population lived in overcrowded housing in 2025, highlighting ongoing housing pressure.",
        confidence="medium",
        used_claude=True,
    )

    assert _is_allowed_medium_claude_editorial_promotion(context, result) is True


def test_high_confidence_claude_editorial_rejection_is_protected_for_uk_construction_statistics_story() -> None:
    context = _make_context(
        title="£1.25bn housing and demolition framework launched",
        preview="LHC Procurement Group has launched a £1.25bn housing, regeneration and demolition framework for public sector clients across the UK.",
        source_id="construction_news_intelligence_listing",
        metadata={"market_scope": "uk_construction_market"},
        event_flags={"construction_news_intelligence_signal": True, "quantified_scale_signal": True},
        score=52,
    )

    assert _should_protect_from_high_confidence_claude_editorial_rejection(context) is True


def test_high_confidence_claude_editorial_rejection_is_not_protected_for_transport_framework_story() -> None:
    context = _make_context(
        title="Three firms get places on £700m London transport framework",
        preview="Amey, Costain and Dragados have won places on Transport for London's infrastructure improvement framework, worth up to £700m.",
        source_id="construction_news_intelligence_listing",
        metadata={"market_scope": "uk_construction_market"},
        event_flags={"construction_news_intelligence_signal": True, "quantified_scale_signal": True},
        score=58,
    )

    assert _should_protect_from_high_confidence_claude_editorial_rejection(context) is False


def test_high_confidence_claude_editorial_rejection_is_protected_for_timber_project_delivery_story() -> None:
    context = _make_context(
        title="22-Storey Mass Timber Pod Hotel Targets Vancouver's Howe Street",
        preview="The 408-unit project has entered Vancouver's rezoning process through a formal application.",
        source_id="wood_central_api",
        metadata={},
        event_flags={"timber_policy_signal": True},
        score=51,
    )

    assert _should_protect_from_high_confidence_claude_editorial_rejection(context) is True


def test_high_confidence_claude_editorial_rejection_is_protected_for_timber_strategic_shift_story() -> None:
    context = _make_context(
        title="Mass timber architects turn from glass as developers revisit facade materials",
        preview=(
            "Architects are shifting away from glass and concrete toward mass timber, with developers weighing "
            "material choices, embodied carbon and commercial adoption."
        ),
        source_id="wood_central_api",
        metadata={},
        event_flags={"timber_strategic_signal": True},
        score=51,
    )

    assert _should_protect_from_high_confidence_claude_editorial_rejection(context) is True
    assert _should_fallback_to_protected_market_signal_after_final_card_invalid_output(context) is True


def test_uk_market_story_is_not_forced_to_skip_claude_final_card() -> None:
    context = _make_context(
        title="Fusion21 opens bidding for £350m repairs framework",
        preview="Fusion21 has invited bids for a £350m responsive repairs and void property framework covering social housing work across the UK.",
        source_id="construction_news_intelligence_listing",
        metadata={"market_scope": "uk_construction_market"},
        event_flags={"construction_news_intelligence_signal": True, "quantified_scale_signal": True},
        score=52,
    )

    assert _should_skip_claude_final_card(context) is False


def test_industrial_automation_partnership_is_not_forced_to_skip_claude_final_card() -> None:
    context = _make_context(
        title="Comau partners with Omron to accelerate advanced industrial automation",
        preview="Comau and Omron Robotics signed a strategic collaboration agreement focused on industrial automation deployments.",
        source_id="robotics_automation_news_rss",
        metadata={"market_scope": "industrial_automation"},
        event_flags={"partnership_event": True, "industrial_robotics_signal": True},
        editorial_flags={"industrial_automation_partnership_signal": True},
        score=69,
    )

    assert _should_skip_claude_final_card(context) is False


def test_robot_data_infrastructure_still_skips_claude_final_card() -> None:
    context = _make_context(
        title="Tutor Intelligence builds Data Factory to train robot AI in the real world",
        preview="Tutor Intelligence is running 100 robots to create real-world training data for robot AI systems.",
        source_id="robot_data_feed",
        metadata={"market_scope": "robotics"},
        event_flags={"factory_opening_or_expansion": True, "industrial_robotics_signal": True},
        editorial_flags={"robot_ai_training_infrastructure_signal": True},
        score=78,
    )

    assert _should_skip_claude_final_card(context) is True


def test_strong_robotics_funding_story_still_uses_claude_final_card() -> None:
    context = _make_context(
        title="Mind Robotics announces $400M in new funding to expand industrial robotics deployment",
        preview="Industrial robotics startup Mind Robotics has raised $400 million in new funding led by Kleiner Perkins.",
        source_id="ai_insider_rss",
        metadata={"tags": ["tech", "funding", "robotics"], "broad_feed": True},
        event_flags={
            "funding_event": True,
            "deployment_event": True,
            "industrial_robotics_signal": True,
            "physical_industry_ai_megafunding_signal": True,
            "quantified_scale_signal": True,
        },
        editorial_flags={"telegram_worthy": True, "industrial_relevance": True},
        score=86,
    )

    assert _should_skip_claude_final_card(context) is False


def test_claude_final_card_invalid_output_reason_is_dropped() -> None:
    assert _should_drop_after_claude_final_card_error(
        "Claude final-card response summary must not contain raw URLs."
    ) is True


def test_claude_final_card_transport_error_reason_falls_back() -> None:
    assert _should_drop_after_claude_final_card_error("Claude request failed: timed out") is False


def test_strong_industrial_funding_story_does_not_fallback_after_claude_reject() -> None:
    context = _make_context(
        title="Mind Robotics announces $400M in new funding to expand industrial robotics deployment",
        preview="Industrial robotics startup Mind Robotics has raised $400 million in new funding led by Kleiner Perkins.",
        source_id="ai_insider_rss",
        metadata={"tags": ["tech", "funding", "robotics"], "broad_feed": True},
        event_flags={
            "funding_event": True,
            "deployment_event": True,
            "industrial_robotics_signal": True,
            "physical_industry_ai_megafunding_signal": True,
            "quantified_scale_signal": True,
        },
        editorial_flags={"telegram_worthy": True, "industrial_relevance": True},
        score=86,
    )

    assert _should_fallback_after_claude_final_card_rejection(context) is False


def test_non_robotics_funding_story_does_not_fallback_after_thin_final_card_reject() -> None:
    context = _make_context(
        title="Enterprise AI startup raises $400M for office productivity tools",
        preview="The company raised $400 million to expand assistants for customer support and internal workflows.",
        source_id="tech_feed",
        metadata={"tags": ["tech", "funding"], "broad_feed": True},
        event_flags={
            "funding_event": True,
            "quantified_scale_signal": True,
            "industrial_robotics_signal": False,
            "physical_industry_ai_megafunding_signal": False,
        },
        editorial_flags={"telegram_worthy": True},
        score=58,
    )

    assert _should_fallback_after_claude_final_card_rejection(context) is False


def test_editorial_promotion_can_fallback_after_final_card_invalid_output() -> None:
    context = _make_context(
        title="Exclusive: Xpanner Lands $18M To Offer Automation As A Service To Construction Sites",
        preview="Xpanner, a startup automating construction work through robotics and physical AI technology, has raised $18 million in a Series B round.",
        source_id="crunchbase_news_listing",
        metadata={"broad_feed": True, "tags": ["construction", "robotics", "funding"]},
        event_flags={
            "funding_event": True,
            "industrial_robotics_signal": True,
            "physical_industry_ai_megafunding_signal": True,
            "quantified_scale_signal": True,
        },
        editorial_flags={"telegram_worthy": True, "strategic_industrial_ai_alert_signal": True},
        score=66,
    )
    context.decision = RankedDecision(
        relevance_status=context.decision.relevance_status,
        send_status=context.decision.send_status,
        skip_reason=context.decision.skip_reason,
        score=context.decision.score,
        signals={**context.decision.signals, "claude_editorial_promoted": True},
        is_shortlisted=context.decision.is_shortlisted,
        is_borderline=context.decision.is_borderline,
    )
    context.final_headline = "Xpanner raises $18M for construction-site automation"
    context.final_summary_text = (
        "Xpanner has raised $18 million in a Series B round to expand robotics and physical AI systems for construction-site automation."
    )

    assert _should_fallback_to_editorial_promotion_after_final_card_invalid_output(context) is True


def test_official_statistics_story_can_fallback_after_final_card_invalid_output() -> None:
    context = _make_context(
        title="Auftragseingang im Bauhauptgewerbe im Mai 2026: +7,3 % zum Vormonat",
        preview=(
            "Der reale Auftragseingang im Bauhauptgewerbe ist im Mai 2026 gegenuber April 2026 gestiegen."
        ),
        source_id="destatis_press_listing",
        metadata={"market_scope": "germany_housing_market", "origin_language": "de"},
        event_flags={"construction_statistics_signal": True},
        score=63,
    )

    assert _should_fallback_to_protected_market_signal_after_final_card_invalid_output(context) is True
