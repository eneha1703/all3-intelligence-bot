"""Daily web-discovery orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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


def _looks_like_evergreen_content(candidate: DiscoveryCandidate) -> bool:
    title = candidate.title.lower()
    url = candidate.url.lower()
    return any(marker in title for marker in EVERGREEN_TITLE_MARKERS) or any(
        marker.replace(" ", "-") in url for marker in EVERGREEN_TITLE_MARKERS
    )


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
    for date_format in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
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
            evaluated.append(
                EvaluatedDiscoveryCandidate(
                    candidate=candidate,
                    dedupe=dedupe,
                    accepted_for_review=rejection_reason is None,
                    rejection_reason=rejection_reason,
                )
            )
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
