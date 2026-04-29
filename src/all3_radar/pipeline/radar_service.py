"""End-to-end News Radar collection and sending service for Bot 1."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.config.loader import load_settings
from all3_radar.delivery.telegram import TelegramSender, build_news_card
from all3_radar.domain.enums import FreshnessStatus, PipelineName, PipelineStatus
from all3_radar.domain.models import (
    ClusterAssignment,
    CompetitorMatch,
    FreshnessEvaluation,
    NormalizedItem,
    RadarRunResult,
    RankedDecision,
    SourceDefinition,
    StoredNormalizedItem,
    SummaryResult,
)
from all3_radar.observability.logging import configure_logging
from all3_radar.observability.run_summary import format_radar_run_summary
from all3_radar.pipeline.collect import build_adapters, collect_from_source, log_source_inventory
from all3_radar.pipeline.competitors import detect_competitor_matches, load_competitor_catalog
from all3_radar.pipeline.dedupe import ClusterResult, ClusterableRecord, cluster_records
from all3_radar.pipeline.editorial import evaluate_send_stage_editorial
from all3_radar.pipeline.freshness import evaluate_freshness
from all3_radar.pipeline.funding_sent_history import funding_key_from_candidate
from all3_radar.pipeline.normalize import normalize_collected_item
from all3_radar.pipeline.ranking import load_ranking_rules, rank_item
from all3_radar.pipeline.run_audit_report import write_run_audit_report
from all3_radar.pipeline.send_stage_dedupe import candidate_from_item, suppress_same_event_funding_duplicates
from all3_radar.sources.base import FetchText
from all3_radar.sources.registry import SourceRegistry, load_source_registry
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository
from all3_radar.summarization.gemini_client import GeminiClient
from all3_radar.summarization.radar_summary import summarize_candidate

LOGGER = logging.getLogger(__name__)


@dataclass
class CurrentRunContext:
    source: SourceDefinition
    item: StoredNormalizedItem
    freshness: FreshnessEvaluation
    competitor_matches: list[CompetitorMatch] = field(default_factory=list)
    cluster_assignment: ClusterAssignment | None = None
    decision: RankedDecision | None = None
    summary: SummaryResult | None = None
    already_sent: bool = False


def _settings_snapshot(settings: object) -> dict:
    snapshot = asdict(settings)
    snapshot["app"]["database_path"] = str(snapshot["app"]["database_path"])
    snapshot["integrations"]["gemini_api_key"] = "***" if snapshot["integrations"]["gemini_api_key"] else None
    snapshot["integrations"]["telegram_alert_bot_token"] = (
        "***" if snapshot["integrations"]["telegram_alert_bot_token"] else None
    )
    return snapshot


def _stored_from_normalized(raw_item_id: str, normalized_item_id: str, item: NormalizedItem) -> StoredNormalizedItem:
    return StoredNormalizedItem(
        normalized_item_id=normalized_item_id,
        raw_item_id=raw_item_id,
        source_id=item.source_id,
        canonical_url=item.canonical_url,
        domain=item.domain,
        title=item.title,
        text_preview=item.text_preview,
        published_ts=item.published_ts,
        collected_ts=item.collected_ts,
        layer=item.layer,
        is_wrapper=item.is_wrapper,
        directness_rank=item.directness_rank,
        metadata=item.metadata,
    )


class RadarService:
    def __init__(
        self,
        repo_root: Path,
        registry: SourceRegistry | None = None,
        repository: RadarRepository | None = None,
        fetch_text_fn: FetchText | None = None,
        gemini_client: GeminiClient | None = None,
        telegram_sender: TelegramSender | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.settings = load_settings(repo_root)
        configure_logging(self.settings.app.log_level)
        self.registry = registry or load_source_registry(repo_root / "config" / "sources.yaml")
        self.repository = repository or RadarRepository(self.settings.app.database_path)
        self.fetch_text_fn = fetch_text_fn
        self.gemini_client = gemini_client or GeminiClient(
            api_key=self.settings.integrations.gemini_api_key,
            model=self.settings.integrations.gemini_model,
        )
        self.telegram_sender = telegram_sender or TelegramSender(
            bot_token=self.settings.integrations.telegram_alert_bot_token,
            chat_ids=self.settings.integrations.telegram_alert_chat_ids,
        )
        initialize_database(self.settings.app.database_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")

    def run(self, source_id: str | None = None, dry_run: bool = False) -> RadarRunResult:
        selected_sources = self.registry.selected(source_id)
        unsupported_sources = self.registry.unsupported_first_slice(selected_sources)
        log_source_inventory(self.registry.all(), selected_sources)

        self.repository.upsert_sources(self.registry.all())
        run_id = self.repository.create_pipeline_run(PipelineName.RADAR, _settings_snapshot(self.settings))
        adapters = build_adapters(fetch_text_fn=self.fetch_text_fn)
        now = datetime.now(timezone.utc)

        contexts: list[CurrentRunContext] = []
        collected_count = 0
        normalized_count = 0
        fresh_count = 0
        stale_count = 0
        missing_published_count = 0
        sent_count = 0
        skipped_send_count = 0
        failed_sources = 0
        source_audit_rows: list[dict[str, object]] = []

        try:
            for source in selected_sources:
                if not source.supports_first_slice:
                    LOGGER.info(
                        "Skipping source in first slice: id=%s kind=%s reason=unsupported_for_initial_collection",
                        source.id,
                        source.kind.value,
                    )
                    continue

                try:
                    items = collect_from_source(source=source, adapters=adapters, collected_at=now)
                except Exception as exc:
                    failed_sources += 1
                    source_audit_rows.append(
                        {
                            "source_id": source.id,
                            "source_name": source.name,
                            "status": f"failed: {exc}",
                            "items_collected": 0,
                        }
                    )
                    LOGGER.warning("Source collection failed: id=%s reason=%s", source.id, exc)
                    continue
                LOGGER.info("Collected items from source: id=%s count=%s", source.id, len(items))
                source_audit_rows.append(
                    {
                        "source_id": source.id,
                        "source_name": source.name,
                        "status": "ok",
                        "items_collected": len(items),
                    }
                )

                source_normalized_count = 0
                for item in items:
                    collected_count += 1
                    raw_item_id = self.repository.insert_raw_item(run_id, item)
                    normalized = normalize_collected_item(source, item)
                    if normalized is None:
                        LOGGER.info("Skipping malformed item during normalization: source=%s url=%s", source.id, item.url)
                        continue

                    normalized_item_id = self.repository.insert_normalized_item(raw_item_id, normalized)
                    stored_item = _stored_from_normalized(raw_item_id, normalized_item_id, normalized)
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
                    else:
                        missing_published_count += 1

                    contexts.append(CurrentRunContext(source=source, item=stored_item, freshness=freshness))

                LOGGER.info(
                    "Source processing summary: id=%s collected=%s normalized=%s",
                    source.id,
                    len(items),
                    source_normalized_count,
                )

            competitor_catalog = load_competitor_catalog(self.repo_root / "config" / "competitors.yaml")
            current_ids = {context.item.normalized_item_id for context in contexts}
            historical_items = [
                item
                for item in self.repository.load_recent_items_for_dedupe()
                if item.normalized_item_id not in current_ids
            ]
            source_priority_map = {source.id: source.priority for source in self.registry.all()}

            for context in contexts:
                matches = detect_competitor_matches(
                    title=context.item.title,
                    preview=context.item.text_preview,
                    catalog=competitor_catalog,
                )
                context.competitor_matches = matches
                self.repository.insert_competitor_matches(context.item.normalized_item_id, matches)
                if matches:
                    matched_names = sorted({match.competitor_name for match in matches})
                    LOGGER.info(
                        "Competitor matches: item=%s competitors=%s",
                        context.item.normalized_item_id,
                        ", ".join(matched_names),
                    )

            cluster_result = cluster_records(
                current_records=[
                    ClusterableRecord(
                        item=context.item,
                        source_priority=source_priority_map.get(context.source.id, context.source.priority),
                        competitor_count=len({match.competitor_name for match in context.competitor_matches}),
                        current_run=True,
                    )
                    for context in contexts
                ],
                historical_records=[
                    ClusterableRecord(
                        item=item,
                        source_priority=source_priority_map.get(item.source_id, 0),
                        competitor_count=self.repository.load_competitor_match_count(item.normalized_item_id),
                        current_run=False,
                        canonical_event_id=item.canonical_event_id,
                    )
                    for item in historical_items
                ],
            )

            assignments_by_event: dict[str, ClusterAssignment] = {}
            for context in contexts:
                assignment = cluster_result.assignments[context.item.normalized_item_id]
                context.cluster_assignment = assignment
                assignments_by_event.setdefault(assignment.canonical_event_id, assignment)
                LOGGER.info(
                    "Dedupe decision: item=%s event=%s current_rep=%s cluster_rep=%s reason=%s",
                    context.item.normalized_item_id,
                    assignment.canonical_event_id,
                    assignment.is_current_run_representative,
                    assignment.is_cluster_representative,
                    assignment.duplicate_reason or "representative",
                )

            for event_id, assignment in assignments_by_event.items():
                self.repository.upsert_canonical_event(
                    assignment=assignment,
                    members=cluster_result.members_by_event_id[event_id],
                    published_values=cluster_result.published_by_event_id[event_id],
                )

            ranking_rules = load_ranking_rules(self.repo_root / "config" / "ranking_rules.yaml")
            shortlisted_contexts: list[CurrentRunContext] = []

            for context in contexts:
                competitor_count = len({match.competitor_name for match in context.competitor_matches})
                if context.cluster_assignment and not context.cluster_assignment.is_current_run_representative:
                    context.decision = RankedDecision(
                        relevance_status="keep",
                        send_status="skip",
                        skip_reason=context.cluster_assignment.duplicate_reason,
                        score=0,
                        signals={"duplicate_of": context.cluster_assignment.representative_item_id},
                        is_shortlisted=False,
                        is_borderline=False,
                    )
                else:
                    already_sent_event = (
                        context.cluster_assignment is not None
                        and self.repository.has_sent_alert_for_event(context.cluster_assignment.canonical_event_id)
                    )
                    already_sent_url = self.repository.has_sent_alert_for_url(context.item.canonical_url)
                    context.decision = rank_item(
                        item=context.item,
                        competitor_count=competitor_count,
                        freshness_is_fresh=context.freshness.is_fresh,
                        ranking_rules=ranking_rules,
                    )
                    funding_match = None
                    if not already_sent_event and not already_sent_url:
                        semantic_funding_key = funding_key_from_candidate(context.item, context.decision)
                        if semantic_funding_key is not None:
                            funding_match = self.repository.find_sent_alert_for_same_funding_event(semantic_funding_key)
                            if funding_match is not None:
                                LOGGER.info(
                                    "Cross-run funding sent-history suppression: item=%s previous_item=%s previous_event=%s previous_url=%s",
                                    context.item.normalized_item_id,
                                    funding_match["normalized_item_id"],
                                    funding_match["canonical_event_id"] or "<none>",
                                    funding_match["canonical_url"],
                                )
                    context.already_sent = already_sent_event or already_sent_url or funding_match is not None
                    if context.already_sent:
                        skip_reason = "already_sent_same_funding_event"
                        if already_sent_event:
                            skip_reason = "already_sent_canonical_event"
                        elif already_sent_url:
                            skip_reason = "already_sent_story_url"
                        context.decision = RankedDecision(
                            relevance_status=context.decision.relevance_status,
                            send_status="skip",
                            skip_reason=skip_reason,
                            score=context.decision.score,
                            signals={
                                **context.decision.signals,
                                "already_sent": True,
                                "already_sent_canonical_event": already_sent_event,
                                "already_sent_story_url": already_sent_url,
                                "already_sent_same_funding_event": funding_match is not None,
                                "already_sent_previous_item_id": (
                                    funding_match["normalized_item_id"] if funding_match is not None else None
                                ),
                                "already_sent_previous_event_id": (
                                    funding_match["canonical_event_id"] if funding_match is not None else None
                                ),
                            },
                            is_shortlisted=False,
                            is_borderline=False,
                        )

                LOGGER.info(
                    "Ranking decision: item=%s score=%s relevance=%s send_status=%s reason=%s",
                    context.item.normalized_item_id,
                    context.decision.score,
                    context.decision.relevance_status,
                    context.decision.send_status,
                    context.decision.skip_reason or "eligible",
                )
                if context.decision.is_shortlisted and context.decision.relevance_status == "keep":
                    shortlisted_contexts.append(context)

            shortlisted_contexts.sort(key=lambda context: context.decision.score if context.decision else 0, reverse=True)
            shortlisted_contexts = shortlisted_contexts[: self.settings.radar.shortlist_size_before_gemini]

            send_threshold = ranking_rules["thresholds"]["send_min_score"]
            sendable_contexts: list[CurrentRunContext] = []
            for context in shortlisted_contexts:
                context.summary = summarize_candidate(context.item, context.decision, self.gemini_client)
                if context.summary.gemini_decision_override == "drop":
                    context.decision = RankedDecision(
                        relevance_status="drop",
                        send_status="skip",
                        skip_reason="gemini_borderline_drop",
                        score=context.decision.score,
                        signals={**context.decision.signals, "gemini_override": "drop"},
                        is_shortlisted=False,
                        is_borderline=False,
                    )
                    continue
                if not (
                    context.decision.relevance_status == "keep"
                    and context.decision.score >= send_threshold
                    and context.decision.send_status != "skip"
                ):
                    continue

                editorial = evaluate_send_stage_editorial(context.item, context.decision)
                if not editorial.allow_send:
                    context.decision = RankedDecision(
                        relevance_status=context.decision.relevance_status,
                        send_status="stored_only",
                        skip_reason=editorial.reason,
                        score=context.decision.score,
                        signals={**context.decision.signals, "editorial_flags": editorial.flags},
                        is_shortlisted=context.decision.is_shortlisted,
                        is_borderline=context.decision.is_borderline,
                    )
                    LOGGER.info(
                        "Editorial shaping decision: item=%s allow_send=%s reason=%s",
                        context.item.normalized_item_id,
                        False,
                        editorial.reason,
                    )
                    continue

                context.decision = RankedDecision(
                    relevance_status=context.decision.relevance_status,
                    send_status=context.decision.send_status,
                    skip_reason=context.decision.skip_reason,
                    score=context.decision.score,
                    signals={**context.decision.signals, "editorial_flags": editorial.flags},
                    is_shortlisted=context.decision.is_shortlisted,
                    is_borderline=context.decision.is_borderline,
                )
                LOGGER.info(
                    "Editorial shaping decision: item=%s allow_send=%s reason=%s",
                    context.item.normalized_item_id,
                    True,
                    "eligible",
                )
                sendable_contexts.append(context)

            sendable_contexts.sort(key=lambda context: context.decision.score if context.decision else 0, reverse=True)
            suppressed_duplicates = suppress_same_event_funding_duplicates(
                [
                    candidate_from_item(context.item, context.decision)
                    for context in sendable_contexts
                    if context.decision is not None
                ]
            )
            if suppressed_duplicates:
                suppressed_by_id = {item.suppressed_item_id: item for item in suppressed_duplicates}
                filtered_sendable_contexts: list[CurrentRunContext] = []
                for context in sendable_contexts:
                    suppression = suppressed_by_id.get(context.item.normalized_item_id)
                    if suppression is None:
                        filtered_sendable_contexts.append(context)
                        continue
                    skipped_send_count += 1
                    context.decision = RankedDecision(
                        relevance_status=context.decision.relevance_status,
                        send_status="skip",
                        skip_reason=suppression.reason,
                        score=context.decision.score,
                        signals={
                            **context.decision.signals,
                            "duplicate_same_event_representative": suppression.representative_item_id,
                        },
                        is_shortlisted=context.decision.is_shortlisted,
                        is_borderline=context.decision.is_borderline,
                    )
                    LOGGER.info(
                        "Late send-stage duplicate suppression: item=%s representative=%s reason=%s",
                        context.item.normalized_item_id,
                        suppression.representative_item_id,
                        suppression.reason,
                    )
                sendable_contexts = filtered_sendable_contexts
            sendable_contexts = sendable_contexts[: self.settings.radar.max_cards_per_run]

            for context in contexts:
                if context.summary is None and context.decision and context.decision.is_shortlisted:
                    context.summary = summarize_candidate(context.item, context.decision, self.gemini_client)

            for context in sendable_contexts:
                card = build_news_card(
                    headline=context.item.title,
                    summary_text=context.summary.summary_text if context.summary else None,
                    url=context.item.canonical_url,
                )
                if card is None:
                    context.decision = RankedDecision(
                        relevance_status=context.decision.relevance_status,
                        send_status="skip",
                        skip_reason="weak_or_empty_telegram_card",
                        score=context.decision.score,
                        signals=context.decision.signals,
                        is_shortlisted=context.decision.is_shortlisted,
                        is_borderline=context.decision.is_borderline,
                    )
                    skipped_send_count += 1
                    LOGGER.info("Send skip: item=%s reason=weak_or_empty_telegram_card", context.item.normalized_item_id)
                    continue

                if dry_run:
                    LOGGER.info("Dry-run send candidate: item=%s", context.item.normalized_item_id)
                    continue

                deliveries = self.telegram_sender.send_card(card)
                any_sent = False
                for delivery in deliveries:
                    self.repository.record_telegram_delivery(
                        run_id=run_id,
                        normalized_item_id=context.item.normalized_item_id,
                        canonical_event_id=context.cluster_assignment.canonical_event_id,
                        chat_id=delivery.chat_id,
                        status=delivery.status,
                        payload_text=delivery.payload_text,
                        telegram_message_id=delivery.telegram_message_id,
                        error_text=delivery.error_text,
                    )
                    any_sent = any_sent or delivery.status == "sent"
                    LOGGER.info(
                        "Telegram delivery: item=%s status=%s chat_id=%s reason=%s",
                        context.item.normalized_item_id,
                        delivery.status,
                        delivery.chat_id or "<unset>",
                        delivery.error_text or "ok",
                    )

                if any_sent:
                    sent_count += 1
                    context.decision = RankedDecision(
                        relevance_status=context.decision.relevance_status,
                        send_status="sent",
                        skip_reason=None,
                        score=context.decision.score,
                        signals=context.decision.signals,
                        is_shortlisted=context.decision.is_shortlisted,
                        is_borderline=context.decision.is_borderline,
                    )
                else:
                    skipped_send_count += 1
                    context.decision = RankedDecision(
                        relevance_status=context.decision.relevance_status,
                        send_status="skip",
                        skip_reason="telegram_send_failed",
                        score=context.decision.score,
                        signals=context.decision.signals,
                        is_shortlisted=context.decision.is_shortlisted,
                        is_borderline=context.decision.is_borderline,
                    )

            for context in contexts:
                decision = context.decision
                assert decision is not None
                summary = context.summary.summary_text if context.summary else None
                used_gemini = context.summary.used_gemini if context.summary else False
                self.repository.upsert_radar_decision(
                    normalized_item_id=context.item.normalized_item_id,
                    canonical_event_id=context.cluster_assignment.canonical_event_id if context.cluster_assignment else None,
                    freshness=context.freshness,
                    relevance_status=decision.relevance_status,
                    send_status=decision.send_status,
                    skip_reason=decision.skip_reason,
                    score=decision.score,
                    signals=decision.signals,
                    summary_text=summary,
                    used_gemini=used_gemini,
                )
                if decision.send_status == "skip" and not context.already_sent and not dry_run:
                    skipped_send_count += 0

            result = RadarRunResult(
                run_id=run_id,
                selected_sources=len(selected_sources),
                collected_items=collected_count,
                normalized_items=normalized_count,
                fresh_items=fresh_count,
                stale_items=stale_count,
                missing_published_ts=missing_published_count,
                unsupported_sources=len(unsupported_sources),
                canonical_events=len(assignments_by_event),
                shortlisted_items=len(shortlisted_contexts),
                sent_items=sent_count,
                skipped_send_items=skipped_send_count,
                failed_sources=failed_sources,
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
                    "canonical_events": result.canonical_events,
                    "shortlisted_items": result.shortlisted_items,
                    "sent_items": result.sent_items,
                    "skipped_send_items": result.skipped_send_items,
                    "failed_sources": result.failed_sources,
                    "dry_run": dry_run,
                },
            )
            try:
                decision_rows = self.repository.list_radar_decision_details_for_run(run_id)
                report_path = write_run_audit_report(self.repo_root, result, decision_rows, source_audit_rows)
                LOGGER.info("Radar run audit report written: %s", report_path)
            except Exception:
                LOGGER.exception("Failed to write radar run audit report for run_id=%s", run_id)
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
