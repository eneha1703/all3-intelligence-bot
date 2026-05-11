from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import RankedDecision, SourceDefinition, StoredNormalizedItem
from all3_radar.pipeline.radar_service import (
    CurrentRunContext,
    _is_allowed_medium_claude_editorial_promotion,
    _should_protect_from_high_confidence_claude_editorial_rejection,
)
from all3_radar.summarization.claude_editorial_review_client import ClaudeEditorialReviewResult


def _make_context(
    *,
    title: str,
    preview: str,
    source_id: str,
    metadata: dict,
    event_flags: dict,
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
        signals={"competitor_count": 0, "event_flags": event_flags},
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


def test_high_confidence_claude_editorial_rejection_is_protected_for_large_uk_housing_framework_story() -> None:
    context = _make_context(
        title="£1.25bn housing and demolition framework launched",
        preview="LHC Procurement Group has launched a £1.25bn housing, regeneration and demolition framework for public sector clients across the UK.",
        source_id="construction_news_intelligence_listing",
        metadata={"market_scope": "uk_construction_market"},
        event_flags={"construction_news_intelligence_signal": True, "quantified_scale_signal": True},
        score=52,
    )

    assert _should_protect_from_high_confidence_claude_editorial_rejection(context) is True
