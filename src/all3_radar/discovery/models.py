"""Typed models for web discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DiscoveryQueryPack:
    id: str
    name: str
    goal: str
    include_signals: tuple[str, ...]
    exclude_signals: tuple[str, ...]
    queries: tuple[str, ...]
    max_results: int = 5


@dataclass(frozen=True)
class DiscoveryConfig:
    enabled: bool
    provider: str
    freshness_days: int
    max_search_uses: int
    max_candidates_returned: int
    max_new_candidates: int
    query_packs: tuple[DiscoveryQueryPack, ...]


@dataclass(frozen=True)
class DiscoveryRuntimeConfig:
    api_key: str | None
    model: str
    timeout_seconds: int
    max_tokens: int
    max_search_uses: int
    max_candidates_returned: int
    max_new_candidates: int
    blocked_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryCandidate:
    title: str
    url: str
    source_name: str | None
    published_date: str | None
    summary: str | None
    query_pack_id: str
    matched_signal: str | None
    why_relevant: str | None
    confidence: str
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeenUrlMatch:
    table_name: str
    matched_url: str
    item_id: str | None = None
    title: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryDedupeResult:
    canonical_url: str
    seen: bool
    reason: str | None = None
    match: SeenUrlMatch | None = None


@dataclass(frozen=True)
class EvaluatedDiscoveryCandidate:
    candidate: DiscoveryCandidate
    dedupe: DiscoveryDedupeResult
    accepted_for_review: bool
    rejection_reason: str | None = None


@dataclass(frozen=True)
class DiscoveryClientResult:
    candidates: tuple[DiscoveryCandidate, ...]
    raw_response_text: str
    web_search_requests: int
    usage: dict[str, Any]


@dataclass(frozen=True)
class DiscoveryRunResult:
    generated_at: datetime
    provider: str
    model: str
    query_packs: tuple[DiscoveryQueryPack, ...]
    evaluated_candidates: tuple[EvaluatedDiscoveryCandidate, ...]
    accepted_candidates: tuple[EvaluatedDiscoveryCandidate, ...]
    web_search_requests: int
    max_search_uses: int
    report_markdown_path: str | None
    report_json_path: str | None
    raw_response_text: str
    usage: dict[str, Any]
