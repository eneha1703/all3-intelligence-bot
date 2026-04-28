"""Collection orchestration for the first direct-source slice."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind
from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText, SourceAdapter, UnsupportedSourceError
from all3_radar.sources.listing import ListingSourceAdapter
from all3_radar.sources.rss import RssSourceAdapter
from all3_radar.sources.wood_central import WoodCentralApiAdapter

LOGGER = logging.getLogger(__name__)


def build_adapters(fetch_text_fn: FetchText | None = None) -> dict[SourceKind, SourceAdapter]:
    return {
        SourceKind.RSS: RssSourceAdapter(fetch_text_fn=fetch_text_fn),
        SourceKind.LISTING: ListingSourceAdapter(fetch_text_fn=fetch_text_fn),
        SourceKind.API: WoodCentralApiAdapter(fetch_text_fn=fetch_text_fn),
    }


def collect_from_source(
    source: SourceDefinition,
    adapters: dict[SourceKind, SourceAdapter],
    collected_at: datetime | None = None,
) -> list[CollectedRawItem]:
    adapter = adapters.get(source.kind)
    if adapter is None:
        raise UnsupportedSourceError(f"No adapter registered for source kind: {source.kind.value}")
    collected_at = collected_at or datetime.now(timezone.utc)
    return adapter.collect(source=source, collected_at=collected_at)


def log_source_inventory(sources: tuple[SourceDefinition, ...], selected: tuple[SourceDefinition, ...]) -> None:
    disabled_direct_sources = [source for source in sources if source.is_direct_source and not source.enabled]
    LOGGER.info(
        "Loaded source inventory: total=%s enabled_direct=%s selected_for_run=%s disabled_direct=%s",
        len(sources),
        sum(1 for source in sources if source.enabled and source.is_direct_source),
        len(selected),
        len(disabled_direct_sources),
    )
    for source in selected:
        LOGGER.info(
            "Selected source: id=%s name=%s kind=%s url=%s priority=%s",
            source.id,
            source.name,
            source.kind.value,
            source.url,
            source.priority,
        )
    for source in disabled_direct_sources:
        LOGGER.info(
            "Disabled direct source: id=%s reason=%s",
            source.id,
            source.extra_config.get("disabled_reason", "disabled_in_config"),
        )
