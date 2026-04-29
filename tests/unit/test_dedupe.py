from datetime import datetime, timedelta, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import StoredNormalizedItem
from all3_radar.pipeline import dedupe as dedupe_module
from all3_radar.pipeline.dedupe import ClusterableRecord, cluster_records


def _make_item(
    item_id: str,
    title: str,
    url: str,
    layer: SourceLayer,
    is_wrapper: bool,
    *,
    published_ts: datetime | None = None,
    canonical_event_id: str | None = None,
) -> StoredNormalizedItem:
    now = published_ts or datetime.now(timezone.utc)
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
        canonical_event_id=canonical_event_id,
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


def test_current_item_reuses_historical_canonical_event_id_by_title_match() -> None:
    historical_primary = ClusterableRecord(
        item=_make_item(
            "hist-1",
            "Acme launches warehouse robot pilot in Germany",
            "https://example.com/hist-1",
            SourceLayer.DIRECT,
            False,
            canonical_event_id="event-123",
        ),
        source_priority=100,
        competitor_count=1,
        current_run=False,
        canonical_event_id="event-123",
    )
    historical_secondary = ClusterableRecord(
        item=_make_item(
            "hist-2",
            "Coverage round-up for automation vendors",
            "https://example.com/hist-2",
            SourceLayer.GOOGLE_COMPETITOR,
            True,
            canonical_event_id="event-123",
        ),
        source_priority=10,
        competitor_count=0,
        current_run=False,
        canonical_event_id="event-123",
    )
    current = ClusterableRecord(
        item=_make_item(
            "current-1",
            "Acme launches warehouse robot pilot in Germany",
            "https://example.com/current-1",
            SourceLayer.DIRECT,
            False,
        ),
        source_priority=100,
        competitor_count=1,
        current_run=True,
    )

    result = cluster_records([current], [historical_primary, historical_secondary])

    assert result.assignments["current-1"].canonical_event_id == "event-123"


def test_current_item_reuses_historical_canonical_event_id_by_canonical_url_match() -> None:
    historical = ClusterableRecord(
        item=_make_item(
            "hist-url",
            "Vendor announces robotics expansion",
            "https://example.com/shared-url",
            SourceLayer.DIRECT,
            False,
            canonical_event_id="event-url",
        ),
        source_priority=100,
        competitor_count=0,
        current_run=False,
        canonical_event_id="event-url",
    )
    current = ClusterableRecord(
        item=_make_item(
            "current-url",
            "Different headline for same story",
            "https://example.com/shared-url",
            SourceLayer.DIRECT,
            False,
        ),
        source_priority=100,
        competitor_count=0,
        current_run=True,
    )

    result = cluster_records([current], [historical])

    assert result.assignments["current-url"].canonical_event_id == "event-url"


def test_unrelated_current_item_does_not_match_historical_event() -> None:
    historical = ClusterableRecord(
        item=_make_item(
            "hist-unrelated",
            "Robotics vendor opens new lab in Tokyo",
            "https://example.com/hist-unrelated",
            SourceLayer.DIRECT,
            False,
            canonical_event_id="event-unrelated",
        ),
        source_priority=100,
        competitor_count=0,
        current_run=False,
        canonical_event_id="event-unrelated",
    )
    current = ClusterableRecord(
        item=_make_item(
            "current-unrelated",
            "Humanoid startup wins defense contract in Texas",
            "https://example.com/current-unrelated",
            SourceLayer.DIRECT,
            False,
        ),
        source_priority=100,
        competitor_count=0,
        current_run=True,
    )

    result = cluster_records([current], [historical])

    assert result.assignments["current-unrelated"].canonical_event_id != "event-unrelated"
    assert result.assignments["current-unrelated"].duplicate_reason is None


def test_event_window_guard_prevents_historical_match() -> None:
    published_then = datetime.now(timezone.utc) - timedelta(days=11)
    published_now = datetime.now(timezone.utc)
    historical = ClusterableRecord(
        item=_make_item(
            "hist-window",
            "Warehouse automation rollout reaches 100 sites",
            "https://example.com/hist-window",
            SourceLayer.DIRECT,
            False,
            published_ts=published_then,
            canonical_event_id="event-window",
        ),
        source_priority=100,
        competitor_count=0,
        current_run=False,
        canonical_event_id="event-window",
    )
    current = ClusterableRecord(
        item=_make_item(
            "current-window",
            "Warehouse automation rollout reaches 100 sites",
            "https://example.com/current-window",
            SourceLayer.DIRECT,
            False,
            published_ts=published_now,
        ),
        source_priority=100,
        competitor_count=0,
        current_run=True,
    )

    result = cluster_records([current], [historical])

    assert result.assignments["current-window"].canonical_event_id != "event-window"


def test_historical_rows_with_existing_canonical_event_id_are_not_reclustered_between_themselves(
    monkeypatch,
) -> None:
    comparison_count = 0

    def _counting_is_same_event(left: ClusterableRecord, right: ClusterableRecord) -> bool:
        nonlocal comparison_count
        comparison_count += 1
        return False

    monkeypatch.setattr(dedupe_module, "is_same_event", _counting_is_same_event)

    historical_records = [
        ClusterableRecord(
            item=_make_item(
                f"hist-{idx}",
                f"Historical story {idx}",
                f"https://example.com/hist-{idx}",
                SourceLayer.DIRECT,
                False,
                canonical_event_id="event-bulk",
            ),
            source_priority=100,
            competitor_count=0,
            current_run=False,
            canonical_event_id="event-bulk",
        )
        for idx in range(20)
    ]
    current = ClusterableRecord(
        item=_make_item(
            "current-bulk",
            "Current story",
            "https://example.com/current-bulk",
            SourceLayer.DIRECT,
            False,
        ),
        source_priority=100,
        competitor_count=0,
        current_run=True,
    )

    cluster_records([current], historical_records)

    assert comparison_count == 20
