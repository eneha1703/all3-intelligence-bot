from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.pipeline.normalize import normalize_collected_item


def test_normalize_collected_item_preserves_source_extra_config() -> None:
    source = SourceDefinition(
        id="business_insider_feed",
        name="Business Insider",
        kind=SourceKind.RSS,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="generic_rss",
        url="https://www.businessinsider.com/rss",
        priority=55,
        tags=("business", "startups"),
        extra_config={"broad_feed": True, "disabled_reason": None},
    )
    now = datetime.now(timezone.utc)
    item = CollectedRawItem(
        source_id=source.id,
        url="https://www.businessinsider.com/story?utm_source=test",
        title="Example story",
        snippet="Example preview.",
        author=None,
        published_ts=now,
        collected_ts=now,
        external_id="story-1",
    )

    normalized = normalize_collected_item(source, item)

    assert normalized is not None
    assert normalized.metadata["broad_feed"] is True
    assert normalized.metadata["parser"] == "generic_rss"


def test_normalize_collected_item_strips_crunchbase_share_prefix_from_snippet() -> None:
    source = SourceDefinition(
        id="crunchbase_news_listing",
        name="Crunchbase News",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="crunchbase_news",
        url="https://news.crunchbase.com/sections/real-estate-property-tech/",
        priority=68,
        tags=("construction", "robotics", "funding"),
    )
    now = datetime.now(timezone.utc)
    item = CollectedRawItem(
        source_id=source.id,
        url="https://news.crunchbase.com/real-estate-property-tech/xpanner-automation-as-a-service-for-construction-sites-startup-funding-physical-ai-robotics/",
        title="Exclusive: Xpanner Lands $18M To Offer Automation As A Service To Construction Sites",
        snippet="0 Shares Email Facebook Twitter LinkedIn Xpanner, a startup automating construction work through robotics and physical AI technology, has raised $18 million in a Series B round.",
        author=None,
        published_ts=now,
        collected_ts=now,
        external_id="xpanner-story",
    )

    normalized = normalize_collected_item(source, item)

    assert normalized is not None
    assert normalized.text_preview is not None
    assert normalized.text_preview.startswith("Xpanner, a startup automating construction work")
    assert "0 Shares Email Facebook Twitter LinkedIn" not in normalized.text_preview
