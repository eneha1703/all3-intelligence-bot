from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import StoredNormalizedItem
from all3_radar.pipeline.dedupe import ClusterableRecord, cluster_records


def _make_item(item_id: str, title: str, url: str, layer: SourceLayer, is_wrapper: bool) -> StoredNormalizedItem:
    now = datetime.now(timezone.utc)
    return StoredNormalizedItem(
        normalized_item_id=item_id,
        raw_item_id=f"raw-{item_id}",
        source_id=f"source-{item_id}",
        canonical_url=url,
        domain="example.com",
        title=title,
        text_preview="Preview text",
        published_ts=now,
        collected_ts=now,
        layer=layer,
        is_wrapper=is_wrapper,
        directness_rank=100 if layer == SourceLayer.DIRECT else 10,
        metadata={},
    )


def test_canonical_dedupe_prefers_direct_source_representative() -> None:
    direct = ClusterableRecord(
        item=_make_item(
            "direct-1",
            "Kewazo raises funding for construction robot rollout",
            "https://direct.example/story",
            SourceLayer.DIRECT,
            False,
        ),
        source_priority=100,
        competitor_count=1,
        current_run=True,
    )
    wrapper = ClusterableRecord(
        item=_make_item(
            "wrapper-1",
            "Google News: Kewazo raises funding for construction robot rollout",
            "https://news.google.com/story",
            SourceLayer.GOOGLE_COMPETITOR,
            True,
        ),
        source_priority=10,
        competitor_count=1,
        current_run=True,
    )

    result = cluster_records([direct, wrapper], [])

    assert result.assignments["direct-1"].canonical_event_id == result.assignments["wrapper-1"].canonical_event_id
    assert result.assignments["direct-1"].is_cluster_representative is True
    assert result.assignments["wrapper-1"].is_cluster_representative is False
    assert result.assignments["wrapper-1"].duplicate_reason == "duplicate_canonical_event"
