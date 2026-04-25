"""Domain model definitions for news items, runs, and source configs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from all3_radar.domain.enums import FreshnessStatus, SourceKind, SourceLayer


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    name: str
    kind: SourceKind
    layer: SourceLayer
    is_direct_source: bool
    is_wrapper: bool
    enabled: bool
    parser: str
    url: str
    priority: int
    tags: tuple[str, ...] = ()
    extra_config: dict[str, Any] = field(default_factory=dict)

    @property
    def is_google_competitor(self) -> bool:
        return self.layer == SourceLayer.GOOGLE_COMPETITOR

    @property
    def supports_first_slice(self) -> bool:
        return self.enabled and self.is_direct_source and self.kind == SourceKind.RSS


@dataclass(frozen=True)
class CollectedRawItem:
    source_id: str
    url: str
    title: str
    snippet: str | None
    author: str | None
    published_ts: datetime | None
    collected_ts: datetime
    external_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedItem:
    source_id: str
    canonical_url: str
    domain: str
    title: str
    dek: str | None
    text_preview: str | None
    published_ts: datetime | None
    collected_ts: datetime
    language: str | None
    layer: SourceLayer
    is_wrapper: bool
    directness_rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FreshnessEvaluation:
    status: FreshnessStatus
    is_fresh: bool
    reason: str


@dataclass(frozen=True)
class RadarRunResult:
    run_id: str
    selected_sources: int
    collected_items: int
    normalized_items: int
    fresh_items: int
    stale_items: int
    missing_published_ts: int
    unsupported_sources: int
