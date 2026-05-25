"""Daily web-discovery orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from all3_radar.config.loader import load_settings
from all3_radar.discovery.claude_web_search import ClaudeWebDiscoveryClient
from all3_radar.discovery.config import load_discovery_config, load_discovery_runtime_config
from all3_radar.discovery.models import (
    DiscoveryCandidate,
    DiscoveryClientResult,
    DiscoveryConfig,
    DiscoveryDedupeResult,
    DiscoveryRuntimeConfig,
    DiscoveryRunResult,
    EvaluatedDiscoveryCandidate,
)
from all3_radar.discovery.report import write_discovery_outputs
from all3_radar.discovery.tavily_search import TavilyWebDiscoveryClient
from all3_radar.pipeline.normalize import normalize_url
from all3_radar.storage.repositories import RadarRepository


class DiscoveryClient(Protocol):
    def discover(
        self,
        *,
        query_packs: tuple,
        freshness_days: int,
    ) -> DiscoveryClientResult:
        """Return candidate URLs from a web discovery provider."""


def _canonicalize_url(url: str) -> str:
    normalized = normalize_url(url.strip())
    if normalized.endswith("/") and normalized.count("/") > 2:
        return normalized.rstrip("/")
    return normalized


EVERGREEN_TITLE_MARKERS = (
    "top 10",
    "top ten",
    "report 2026",
    "guide",
    "market overview",
    "applications",
    "trends 2026",
    "what is",
)

LOW_SIGNAL_SOURCE_MARKERS = (
    "partner-content",
    "sponsored",
    "advertorial",
    "medium.com",
    "letsdatascience.com",
)

AUTOMOTIVE_PHYSICAL_AI_MARKERS = (
    "vehicle",
    "vehicles",
    "automotive",
    "adas",
    "in-cabin",
    "driver assistance",
)

DEPLOYMENT_REALITY_MARKERS = (
    "factory",
    "plant",
    "warehouse",
    "site",
    "facility",
    "construction",
    "industrial",
    "production",
)


def _looks_like_evergreen_content(candidate: DiscoveryCandidate) -> bool:
    title = candidate.title.lower()
    url = candidate.url.lower()
    return any(marker in title for marker in EVERGREEN_TITLE_MARKERS) or any(
        marker.replace(" ", "-") in url for marker in EVERGREEN_TITLE_MARKERS
    )


def _looks_like_low_signal_source(candidate: DiscoveryCandidate) -> bool:
    haystacks = (
        candidate.url.lower(),
        (candidate.source_name or "").lower(),
        candidate.title.lower(),
    )
    return any(marker in haystack for haystack in haystacks for marker in LOW_SIGNAL_SOURCE_MARKERS)


def _looks_like_vehicle_ai_story_without_real_deployment(candidate: DiscoveryCandidate) -> bool:
    if candidate.query_pack_id != "industrial_robotics_physical_ai":
        return False
    text = " ".join(
        part
        for part in (
            candidate.title,
            candidate.summary or "",
            candidate.why_relevant or "",
            candidate.matched_signal or "",
        )
    ).lower()
    has_automotive_marker = any(marker in text for marker in AUTOMOTIVE_PHYSICAL_AI_MARKERS)
    has_real_deployment_marker = any(marker in text for marker in DEPLOYMENT_REALITY_MARKERS)
    return has_automotive_marker and not has_real_deployment_marker


def _normalized_title_signature(title: str) -> str:
    filtered = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in title)
    tokens = [token for token in filtered.split() if len(token) > 2]
    return " ".join(tokens)


def _looks_like_near_duplicate_story(left: DiscoveryCandidate, right: DiscoveryCandidate) -> bool:
    if left.query_pack_id != right.query_pack_id:
        return False
    left_signature = _normalized_title_signature(left.title)
    right_signature = _normalized_title_signature(right.title)
    if not left_signature or not right_signature:
        return False
    similarity = SequenceMatcher(None, left_signature, right_signature).ratio()
    if similarity >= 0.78:
        return True
    left_tokens = set(left_signature.split())
    right_tokens = set(right_signature.split())
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= 0.8


def _parse_candidate_date(value: str | None, *, now: datetime) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered == "today":
        return now
    if lowered == "yesterday":
        return now - timedelta(days=1)
    if lowered.endswith("days ago"):
        try:
            return now - timedelta(days=int(lowered.split()[0]))
        except (ValueError, IndexError):
            return None
    if lowered.endswith("day ago"):
        return now - timedelta(days=1)
    if "week ago" in lowered or "weeks ago" in lowered or "month ago" in lowered or "months ago" in lowered:
        return None
    for date_format in (
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %B %Y %H:%M:%S %Z",
    ):
        try:
            parsed = datetime.strptime(normalized, date_format)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _freshness_rejection_reason(
    candidate: DiscoveryCandidate,
    *,
    freshness_days: int,
    now: datetime,
) -> str | None:
    parsed = _parse_candidate_date(candidate.published_date, now=now)
    if parsed is None:
        return "missing_or_unparseable_published_date"
    cutoff = now - timedelta(days=freshness_days)
    if parsed < cutoff:
        return "outside_freshness_window"
    return None


def _candidate_rejection_reason(
    candidate: DiscoveryCandidate,
    dedupe: DiscoveryDedupeResult,
    *,
    freshness_days: int,
    now: datetime,
) -> str | None:
    if dedupe.seen:
        return dedupe.reason or "already_seen_in_bot_history"
    if candidate.confidence not in {"medium", "high"}:
        return "low_confidence"
    freshness_reason = _freshness_rejection_reason(candidate, freshness_days=freshness_days, now=now)
    if freshness_reason:
        return freshness_reason
    if _looks_like_evergreen_content(candidate):
        return "evergreen_or_report_like_content"
    if _looks_like_low_signal_source(candidate):
        return "low_signal_source_or_partner_content"
    if _looks_like_vehicle_ai_story_without_real_deployment(candidate):
        return "automotive_or_vehicle_ai_without_factory_deployment"
    return None


class WebDiscoveryService:
    def __init__(
        self,
        *,
        repository: RadarRepository,
        discovery_config: DiscoveryConfig,
        runtime_config: DiscoveryRuntimeConfig,
        client: DiscoveryClient,
    ) -> None:
        self.repository = repository
        self.discovery_config = discovery_config
        self.runtime_config = runtime_config
        self.client = client

    def run(self, *, output_dir: Path | None = None) -> DiscoveryRunResult:
        if not self.discovery_config.enabled:
            raise RuntimeError("Web discovery is disabled in config/web_discovery.yaml.")

        client_result = self.client.discover(
            query_packs=self.discovery_config.query_packs,
            freshness_days=self.discovery_config.freshness_days,
        )
        generated_at = datetime.now(timezone.utc)
        evaluated = self._evaluate_candidates(client_result.candidates, generated_at=generated_at)
        accepted = tuple(item for item in evaluated if item.accepted_for_review)[: self.runtime_config.max_new_candidates]
        result = DiscoveryRunResult(
            generated_at=generated_at,
            provider=self.discovery_config.provider,
            model=self.runtime_config.model,
            query_packs=self.discovery_config.query_packs,
            evaluated_candidates=evaluated,
            accepted_candidates=accepted,
            web_search_requests=client_result.web_search_requests,
            max_search_uses=self.runtime_config.max_search_uses,
            report_markdown_path=None,
            report_json_path=None,
            raw_response_text=client_result.raw_response_text,
            usage=client_result.usage,
        )
        if output_dir is not None:
            markdown_path, json_path = write_discovery_outputs(result, output_dir)
            result = replace(
                result,
                report_markdown_path=str(markdown_path),
                report_json_path=str(json_path),
            )
        return result

    def _evaluate_candidates(
        self,
        candidates: tuple[DiscoveryCandidate, ...],
        *,
        generated_at: datetime,
    ) -> tuple[EvaluatedDiscoveryCandidate, ...]:
        evaluated: list[EvaluatedDiscoveryCandidate] = []
        seen_in_response: set[str] = set()
        accepted_candidates: list[DiscoveryCandidate] = []
        for candidate in candidates:
            canonical_url = _canonicalize_url(candidate.url)
            if canonical_url in seen_in_response:
                dedupe = DiscoveryDedupeResult(
                    canonical_url=canonical_url,
                    seen=True,
                    reason="duplicate_in_discovery_response",
                    match=None,
                )
            else:
                seen_in_response.add(canonical_url)
                existing = self.repository.find_seen_url(canonical_url)
                dedupe = DiscoveryDedupeResult(
                    canonical_url=canonical_url,
                    seen=existing is not None,
                    reason="already_seen_in_bot_history" if existing is not None else None,
                    match=existing,
                )
            rejection_reason = _candidate_rejection_reason(
                candidate,
                dedupe,
                freshness_days=self.discovery_config.freshness_days,
                now=generated_at,
            )
            if rejection_reason is None:
                duplicate_match = next(
                    (accepted for accepted in accepted_candidates if _looks_like_near_duplicate_story(accepted, candidate)),
                    None,
                )
                if duplicate_match is not None:
                    rejection_reason = "duplicate_in_discovery_response_cluster"
            evaluated.append(
                EvaluatedDiscoveryCandidate(
                    candidate=candidate,
                    dedupe=dedupe,
                    accepted_for_review=rejection_reason is None,
                    rejection_reason=rejection_reason,
                )
            )
            if rejection_reason is None:
                accepted_candidates.append(candidate)
        return tuple(evaluated)


def run_web_discovery(repo_root: Path, *, output_dir: Path | None = None) -> DiscoveryRunResult:
    settings = load_settings(repo_root)
    if not settings.app.database_path.exists():
        raise RuntimeError(
            f"Runtime database not found: {settings.app.database_path}. "
            "Restore the radar DB before running web discovery so URL dedupe has history."
        )
    discovery_config = load_discovery_config(repo_root / "config" / "web_discovery.yaml")
    runtime_config = load_discovery_runtime_config(discovery_config)
    repository = RadarRepository(settings.app.database_path)
    if discovery_config.provider == "claude_web_search":
        client = ClaudeWebDiscoveryClient(runtime_config)
    elif discovery_config.provider == "tavily_search":
        client = TavilyWebDiscoveryClient(runtime_config)
    else:
        raise RuntimeError(f"Unsupported web discovery provider: {discovery_config.provider}")
    return WebDiscoveryService(
        repository=repository,
        discovery_config=discovery_config,
        runtime_config=runtime_config,
        client=client,
    ).run(output_dir=output_dir or repo_root / "data" / "web-discovery")
