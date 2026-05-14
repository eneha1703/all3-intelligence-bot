from datetime import datetime, timedelta, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import NormalizedItem
from all3_radar.pipeline.freshness import evaluate_freshness, resolve_lookback_hours


def _make_item(title: str, preview: str | None = None, **metadata) -> NormalizedItem:
    now = datetime.now(timezone.utc)
    return NormalizedItem(
        source_id="haufe_immobilien_listing",
        canonical_url="https://example.com/story",
        domain="example.com",
        title=title,
        dek=None,
        text_preview=preview,
        published_ts=now,
        collected_ts=now,
        language="de",
        layer=SourceLayer.DIRECT,
        is_wrapper=False,
        directness_rank=100,
        metadata=metadata or {"market_scope": "germany_housing_market"},
    )


def test_haufe_housing_story_gets_extended_lookback() -> None:
    item = _make_item(
        "Neue Koalition will Wohnungsnot angehen",
        "Die Koalition will mit einem Gesetz fuer einfaches Bauen den Wohnungsbau beschleunigen.",
        market_scope="germany_housing_market",
    )

    assert resolve_lookback_hours(item, 24) == 48


def test_non_haufe_story_keeps_default_lookback() -> None:
    item = _make_item(
        "Generic market update",
        "A generic business story.",
        market_scope="germany_housing_market",
    )
    item = NormalizedItem(**{**item.__dict__, "source_id": "tech_eu_rss"})

    assert resolve_lookback_hours(item, 24) == 24


def test_haufe_housing_story_within_48h_is_fresh() -> None:
    now = datetime(2026, 5, 14, 12, 35, tzinfo=timezone.utc)
    published = now - timedelta(hours=30)

    freshness = evaluate_freshness(
        published_ts=published,
        collected_ts=now,
        now=now,
        lookback_hours=48,
        require_published_ts=True,
        allow_collected_at_fallback=False,
    )

    assert freshness.is_fresh is True
