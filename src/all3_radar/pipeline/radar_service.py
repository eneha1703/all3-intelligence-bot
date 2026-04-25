"""End-to-end News Radar collection service for the first Bot 1 slice."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.config.loader import load_settings
from all3_radar.domain.enums import FreshnessStatus, PipelineName, PipelineStatus
from all3_radar.domain.models import RadarRunResult
from all3_radar.observability.logging import configure_logging
from all3_radar.observability.run_summary import format_radar_run_summary
from all3_radar.pipeline.collect import build_adapters, collect_from_source, log_source_inventory
from all3_radar.pipeline.freshness import evaluate_freshness
from all3_radar.pipeline.normalize import normalize_collected_item
from all3_radar.sources.base import FetchText
from all3_radar.sources.registry import SourceRegistry, load_source_registry
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository

LOGGER = logging.getLogger(__name__)


def _settings_snapshot(settings: object) -> dict:
    snapshot = asdict(settings)
    snapshot["app"]["database_path"] = str(snapshot["app"]["database_path"])
    return snapshot


class RadarService:
    def __init__(
        self,
        repo_root: Path,
        registry: SourceRegistry | None = None,
        repository: RadarRepository | None = None,
        fetch_text_fn: FetchText | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.settings = load_settings(repo_root)
        configure_logging(self.settings.app.log_level)
        self.registry = registry or load_source_registry(repo_root / "config" / "sources.yaml")
        self.repository = repository or RadarRepository(self.settings.app.database_path)
        self.fetch_text_fn = fetch_text_fn
        initialize_database(self.settings.app.database_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")

    def run(self, source_id: str | None = None, dry_run: bool = False) -> RadarRunResult:
        selected_sources = self.registry.selected(source_id)
        unsupported_sources = self.registry.unsupported_first_slice(selected_sources)
        log_source_inventory(self.registry.all(), selected_sources)

        self.repository.upsert_sources(self.registry.all())
        run_id = self.repository.create_pipeline_run(PipelineName.RADAR, _settings_snapshot(self.settings))
        adapters = build_adapters(fetch_text_fn=self.fetch_text_fn)
        now = datetime.now(timezone.utc)

        collected_count = 0
        normalized_count = 0
        fresh_count = 0
        stale_count = 0
        missing_published_count = 0

        try:
            for source in selected_sources:
                if not source.supports_first_slice:
                    LOGGER.info(
                        "Skipping source in first slice: id=%s kind=%s reason=unsupported_for_initial_collection",
                        source.id,
                        source.kind.value,
                    )
                    continue

                items = collect_from_source(source=source, adapters=adapters, collected_at=now)
                LOGGER.info("Collected items from source: id=%s count=%s", source.id, len(items))

                source_normalized_count = 0
                for item in items:
                    collected_count += 1
                    raw_item_id = self.repository.insert_raw_item(run_id, item)
                    normalized = normalize_collected_item(source, item)
                    if normalized is None:
                        LOGGER.info("Skipping malformed item during normalization: source=%s url=%s", source.id, item.url)
                        continue

                    normalized_item_id = self.repository.insert_normalized_item(raw_item_id, normalized)
                    normalized_count += 1
                    source_normalized_count += 1

                    freshness = evaluate_freshness(
                        published_ts=normalized.published_ts,
                        collected_ts=normalized.collected_ts,
                        now=now,
                        lookback_hours=self.settings.radar.lookback_hours,
                        require_published_ts=self.settings.radar.require_published_ts,
                        allow_collected_at_fallback=self.settings.radar.allow_collected_at_fallback,
                    )

                    if freshness.status == FreshnessStatus.FRESH:
                        fresh_count += 1
                    elif freshness.status == FreshnessStatus.STALE:
                        stale_count += 1
                    elif freshness.status == FreshnessStatus.MISSING_PUBLISHED_TS:
                        missing_published_count += 1

                    self.repository.upsert_radar_decision(
                        normalized_item_id=normalized_item_id,
                        freshness=freshness,
                        relevance_status="keep" if freshness.is_fresh else "drop",
                        send_status="stored_only" if freshness.is_fresh else "skip",
                        skip_reason=None if freshness.is_fresh else freshness.reason,
                        signals={"source_id": source.id, "dry_run": dry_run, "freshness_reason": freshness.reason},
                    )

                LOGGER.info(
                    "Source processing summary: id=%s collected=%s normalized=%s",
                    source.id,
                    len(items),
                    source_normalized_count,
                )

            result = RadarRunResult(
                run_id=run_id,
                selected_sources=len(selected_sources),
                collected_items=collected_count,
                normalized_items=normalized_count,
                fresh_items=fresh_count,
                stale_items=stale_count,
                missing_published_ts=missing_published_count,
                unsupported_sources=len(unsupported_sources),
            )
            self.repository.finish_pipeline_run(
                run_id,
                PipelineStatus.COMPLETED,
                {
                    "selected_sources": result.selected_sources,
                    "collected_items": result.collected_items,
                    "normalized_items": result.normalized_items,
                    "fresh_items": result.fresh_items,
                    "stale_items": result.stale_items,
                    "missing_published_ts": result.missing_published_ts,
                    "unsupported_sources": result.unsupported_sources,
                    "dry_run": dry_run,
                },
            )
            LOGGER.info("Radar run complete: %s", format_radar_run_summary(result))
            return result
        except Exception:
            self.repository.finish_pipeline_run(
                run_id,
                PipelineStatus.FAILED,
                {"error": "Radar run failed before completion."},
            )
            raise


def run_radar(repo_root: Path, source_id: str | None = None, dry_run: bool = False) -> RadarRunResult:
    service = RadarService(repo_root=repo_root)
    return service.run(source_id=source_id, dry_run=dry_run)
