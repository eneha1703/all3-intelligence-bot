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
