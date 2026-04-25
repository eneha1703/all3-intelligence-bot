from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import StoredNormalizedItem
from all3_radar.pipeline.ranking import derive_event_flags
from all3_radar.pipeline.filters import compute_relevance_status


def _make_item(title: str, preview: str, broad_feed: bool) -> StoredNormalizedItem:
    now = datetime.now(timezone.utc)
    return StoredNormalizedItem(
        normalized_item_id="item-1",
        raw_item_id="raw-1",
        source_id="source-1",
        canonical_url="https://example.com/story",
        domain="example.com",
        title=title,
        text_preview=preview,
        published_ts=now,
        collected_ts=now,
        layer=SourceLayer.DIRECT,
        is_wrapper=False,
        directness_rank=100,
        metadata={"tags": ["tech"], "broad_feed": broad_feed},
    )


def test_broad_feed_requires_clear_all3_scope() -> None:
    item = _make_item(
        "Google to invest up to $40B in Anthropic in cash and compute",
        "Generic AI infrastructure financing story unrelated to buildings, factories, or site operations.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_warehouse_story_without_clear_strategic_scope_is_dropped() -> None:
    item = _make_item(
        "Humanoid robots pilot begins in warehouse operations",
        "A warehouse pilot starts for humanoid robots in logistics workflows.",
        broad_feed=False,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_broad_feed_story_with_generic_factory_language_is_dropped() -> None:
    item = _make_item(
        "AI startups are raising millions to disrupt Hollywood",
        "Studios adopt AI for production and marketing as founders share pitch decks to raise funding.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_broad_feed_story_with_generic_automation_language_is_dropped() -> None:
    item = _make_item(
        "MrBeast is plotting a move into AI-native entertainment",
        "The company wants to build a production team around AI automation for content workflows.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"
