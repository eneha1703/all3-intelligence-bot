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
        return self.enabled and self.is_direct_source and (
            self.kind == SourceKind.RSS
            or (
                self.kind == SourceKind.LISTING
                and self.parser in {"destatis_press", "humanoid_robotics_technology"}
            )
            or (self.kind == SourceKind.API and self.parser == "wood_central_api")
        )


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
class CompetitorMatch:
    competitor_name: str
    alias_matched: str
    match_field: str


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
class StoredNormalizedItem:
    normalized_item_id: str
    raw_item_id: str
    source_id: str
    canonical_url: str
    domain: str
    title: str
    text_preview: str | None
    published_ts: datetime | None
    collected_ts: datetime
    layer: SourceLayer
    is_wrapper: bool
    directness_rank: int
    metadata: dict[str, Any] = field(default_factory=dict)
    canonical_event_id: str | None = None


@dataclass(frozen=True)
class ClusterAssignment:
    canonical_event_id: str
    event_key: str
    cluster_title: str
    is_cluster_representative: bool
    is_current_run_representative: bool
    duplicate_reason: str | None
    representative_item_id: str


@dataclass(frozen=True)
class RankedDecision:
    relevance_status: str
    send_status: str
    skip_reason: str | None
    score: int
    signals: dict[str, Any]
    is_shortlisted: bool
    is_borderline: bool


@dataclass(frozen=True)
class SummaryResult:
    summary_text: str | None
    used_gemini: bool
    gemini_decision_override: str | None = None


@dataclass(frozen=True)
class ClaudeFinalCardResult:
    send_ok: bool
    reject_reason: str | None
    title: str | None
    summary: str | None
    why_it_matters: str | None
    duplicate_risk: str | None
    confidence: str | None
    used_claude: bool
    fallback_reason: str | None = None


@dataclass(frozen=True)
class TelegramCard:
    text: str
    headline: str
    summary_text: str
    url: str
    action_buttons: tuple["TelegramActionButton", ...] = ()


@dataclass(frozen=True)
class TelegramActionButton:
    text: str
    callback_data: str


@dataclass(frozen=True)
class EditorialSignal:
    signal_type: str
    signal_state: str
    source_kind: str
    normalized_item_id: str
    canonical_event_id: str | None
    chat_id: str = ""
    telegram_message_id: str = ""
    user_id: str = ""
    username: str = ""
    raw_value: str | None = None


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
    canonical_events: int
    shortlisted_items: int
    sent_items: int
    skipped_send_items: int
    failed_sources: int
