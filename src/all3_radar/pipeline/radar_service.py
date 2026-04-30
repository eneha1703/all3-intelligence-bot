"""End-to-end News Radar collection and sending service for Bot 1."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

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
from all3_radar.pipeline.deployment_event_key import deployment_key_from_text
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
from all3_radar.summarization.claude_final_card_client import (
    ClaudeFinalCardClient,
    ClaudeFinalCardUnavailableError,
)
from all3_radar.summarization.claude_editorial_review_client import (
    ClaudeEditorialReviewClient,
    ClaudeEditorialReviewUnavailableError,
)
from all3_radar.summarization.radar_summary import summarize_candidate

LOGGER = logging.getLogger(__name__)
KNOWN_CLAUDE_EDITORIAL_FALLBACK_REASONS = {
    "api_http_error",
    "api_timeout",
    "api_network_error",
    "api_json_decode_error",
    "response_not_json",
    "response_empty",
    "response_missing_text",
    "response_missing_send_ok",
    "response_invalid_confidence",
    "response_invalid_rejection",
    "response_invalid_promotion",
    "low_or_medium_confidence",
    "unknown",
}


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
    final_headline: str | None = None
    final_summary_text: str | None = None


def _with_context_signals(context: CurrentRunContext, **updates: object) -> None:
    if context.decision is None:
        return
    merged_signals = {**context.decision.signals, **updates}
    context.decision = RankedDecision(
        relevance_status=context.decision.relevance_status,
        send_status=context.decision.send_status,
        skip_reason=context.decision.skip_reason,
        score=context.decision.score,
        signals=merged_signals,
        is_shortlisted=context.decision.is_shortlisted,
        is_borderline=context.decision.is_borderline,
    )


def _resolve_card_writer_diagnostics(context: CurrentRunContext) -> dict[str, object]:
    if context.decision is None:
        return {}

    signals = context.decision.signals
    outcome = signals.get("claude_final_card_outcome")
    reviewed = bool(signals.get("claude_final_card_reviewed", False))
    title_source = signals.get("final_card_title_source")
    summary_source = signals.get("final_card_summary_source")
    reason = signals.get("claude_final_card_reason")

    if outcome is None:
        reviewed = False
        outcome = "not_attempted"
        reason = None

    if title_source is None:
        title_source = "original_title"

    if summary_source is None:
        if context.final_summary_text and signals.get("claude_editorial_promoted", False):
            summary_source = "claude_editorial_promotion"
        elif context.summary is not None and context.summary.used_gemini:
            summary_source = "gemini_summary"
        else:
            summary_source = "deterministic_summary"

    if context.final_headline and title_source == "claude_final_card":
        card_writer = "claude_final_card"
    elif context.final_headline and title_source == "claude_editorial_promotion":
        card_writer = "claude_editorial_promotion"
    elif outcome in {"fallback_unavailable", "fallback_low_confidence"}:
        if title_source == "claude_editorial_promotion" or summary_source == "claude_editorial_promotion":
            card_writer = "claude_editorial_promotion"
        else:
            card_writer = "deterministic_after_claude_final_card_fallback"
    elif summary_source == "gemini_summary":
        card_writer = "gemini_summary"
    else:
        card_writer = "deterministic_summary"

    return {
        "card_writer": card_writer,
        "final_card_title_source": title_source,
        "final_card_summary_source": summary_source,
        "claude_final_card_reviewed": reviewed,
        "claude_final_card_outcome": outcome,
        "claude_final_card_reason": reason,
    }


def _contains_any_term(haystack: str, terms: tuple[str, ...]) -> bool:
    return any(term in haystack for term in terms)


def _claude_editorial_review_priority(context: CurrentRunContext) -> tuple[int, int]:
    if context.decision is None:
        return (0, 0)

    haystack = f"{context.item.title} {context.item.text_preview or ''}".lower()
    score = context.decision.score
    signals = context.decision.signals
    event_flags = signals.get("event_flags", {})
    if not isinstance(event_flags, dict):
        event_flags = {}

    robotics_business_story = _contains_any_term(
        haystack,
        (
            "teradyne robotics",
            "universal robots",
            "mobile industrial robots",
            " mir ",
            "robotics revenue",
            "robotics segment revenue",
            "robotics segment",
        ),
    ) and _contains_any_term(
        haystack,
        ("revenue", "sales", "orders", "margin", "earnings", "quarter", "q1", "q2", "q3", "q4", "growth", "decline"),
    )
    automation_engineering_story = _contains_any_term(
        haystack,
        (
            "manufacturing language model",
            "industrial automation design",
            "automation engineering",
            "automation cell design",
            "robotics deployment engineering",
            "commissioning",
            "integration",
            "high-mix, low-volume",
        ),
    )
    robotics_infrastructure_story = _contains_any_term(
        haystack,
        (
            "robotics-led infrastructure",
            "data center construction",
            "data centre",
            "physical ai platform",
            "robotics company roze",
            "roze ai",
        ),
    )
    greenhouse_automation_story = _contains_any_term(
        haystack,
        (
            "greenhouse",
            "harvesting robots",
            "robot-ready",
            "horticulture",
            "fully-automated greenhouses",
        ),
    )
    clear_industrial_operating_signal = bool(
        event_flags.get("industrial_robotics_signal")
        or event_flags.get("deployment_event")
        or event_flags.get("factory_opening_or_expansion")
        or robotics_business_story
    )

    consumer_robotaxi_story = _contains_any_term(
        haystack,
        (
            "robotaxi",
            "self-driving",
            "ride-hailing",
            "waymo one",
            "how to ride",
            "crash record",
            "autonomous rides",
            "consumer cars",
        ),
    )
    timber_policy_only_story = bool(event_flags.get("timber_policy_signal")) and not _contains_any_term(
        haystack, ("robot", "automation", "factory", "construction", "housing")
    )
    security_automation_story = _contains_any_term(
        haystack,
        (
            "access control",
            "security automation",
            "industrial iot",
            "iiot",
            "real-time security",
        ),
    )
    procurement_story = _contains_any_term(
        haystack,
        ("procurement automation", "purchase orders", "approval history", "audit-ready supply chains"),
    )
    auction_story = _contains_any_term(
        haystack,
        ("auction", "liquidate", "liquidation", "surplus robots", "asset disposition"),
    )
    generic_business_explainer = _contains_any_term(
        haystack,
        ("here's how", "what does", "who can", "how do", "who are the competitors"),
    )

    if (
        consumer_robotaxi_story
        or timber_policy_only_story
        or security_automation_story
        or procurement_story
        or auction_story
        or generic_business_explainer
    ):
        return (0, score)
    if robotics_business_story or automation_engineering_story or robotics_infrastructure_story or greenhouse_automation_story:
        return (3, score)
    if clear_industrial_operating_signal:
        return (2, score)
    return (1, score)


def _settings_snapshot(settings: object) -> dict:
    snapshot = asdict(settings)
    snapshot["app"]["database_path"] = str(snapshot["app"]["database_path"])
    snapshot["integrations"]["gemini_api_key"] = "***" if snapshot["integrations"]["gemini_api_key"] else None
    snapshot["integrations"]["anthropic_api_key"] = (
        "***" if snapshot["integrations"]["anthropic_api_key"] else None
    )
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
        claude_editorial_review_client: ClaudeEditorialReviewClient | None = None,
        claude_final_card_client: ClaudeFinalCardClient | None = None,
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
        if claude_editorial_review_client is not None:
            self.claude_editorial_review_client = claude_editorial_review_client
        elif self.settings.radar.claude_editorial_enabled:
            self.claude_editorial_review_client = ClaudeEditorialReviewClient(
                enabled=self.settings.radar.claude_editorial_enabled,
                api_key=self.settings.integrations.anthropic_api_key,
                model=self.settings.integrations.claude_editorial_model,
                timeout_seconds=self.settings.integrations.claude_editorial_timeout_seconds,
                max_tokens=self.settings.integrations.claude_editorial_max_tokens,
            )
        else:
            self.claude_editorial_review_client = None
        if claude_final_card_client is not None:
            self.claude_final_card_client = claude_final_card_client
        elif self.settings.radar.claude_final_card_enabled:
            self.claude_final_card_client = ClaudeFinalCardClient(
                enabled=self.settings.radar.claude_final_card_enabled,
                api_key=self.settings.integrations.anthropic_api_key,
                model=self.settings.integrations.claude_final_card_model,
                timeout_seconds=self.settings.integrations.claude_final_card_timeout_seconds,
                max_tokens=self.settings.integrations.claude_final_card_max_tokens,
            )
        else:
            self.claude_final_card_client = None
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
        run_started = perf_counter()

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
        stage_timings: dict[str, float] = {}
        stage_counters: dict[str, int] = {}

        def record_stage_timing(label: str, started: float) -> None:
            stage_timings[label] = stage_timings.get(label, 0.0) + (perf_counter() - started)

        def increment_stage_counter(label: str, amount: int = 1) -> None:
            stage_counters[label] = stage_counters.get(label, 0) + amount

        def record_claude_editorial_fallback(reason: str) -> str:
            sanitized_reason = (
                reason if reason in KNOWN_CLAUDE_EDITORIAL_FALLBACK_REASONS else "unknown"
            )
            increment_stage_counter("claude_editorial_fallback")
            increment_stage_counter(f"claude_editorial_fallback_{sanitized_reason}")
            return sanitized_reason

        try:
            for source in selected_sources:
                if not source.supports_first_slice:
                    LOGGER.info(
                        "Skipping source in first slice: id=%s kind=%s reason=unsupported_for_initial_collection",
                        source.id,
                        source.kind.value,
                    )
                    continue

                source_started = perf_counter()
                try:
                    items = collect_from_source(source=source, adapters=adapters, collected_at=now)
                except Exception as exc:
                    failed_sources += 1
                    duration_seconds = round(perf_counter() - source_started, 3)
                    source_audit_rows.append(
                        {
                            "source_id": source.id,
                            "source_name": source.name,
                            "status": f"failed: {exc}",
                            "items_collected": 0,
                            "duration_seconds": duration_seconds,
                        }
                    )
                    LOGGER.warning("Source collection failed: id=%s reason=%s", source.id, exc)
                    continue
                duration_seconds = round(perf_counter() - source_started, 3)
                LOGGER.info("Collected items from source: id=%s count=%s", source.id, len(items))
                source_audit_rows.append(
                    {
                        "source_id": source.id,
                        "source_name": source.name,
                        "status": "ok",
                        "items_collected": len(items),
                        "duration_seconds": duration_seconds,
                    }
                )

                source_normalized_count = 0
                normalization_started = perf_counter()
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

                record_stage_timing("normalization_and_freshness", normalization_started)
                LOGGER.info(
                    "Source processing summary: id=%s collected=%s normalized=%s",
                    source.id,
                    len(items),
                    source_normalized_count,
                )

            historical_dedupe_started = perf_counter()
            competitor_catalog = load_competitor_catalog(self.repo_root / "config" / "competitors.yaml")
            current_ids = {context.item.normalized_item_id for context in contexts}
            historical_items = [
                item
                for item in self.repository.load_recent_items_for_dedupe()
                if item.normalized_item_id not in current_ids
            ]
            source_priority_map = {source.id: source.priority for source in self.registry.all()}
            record_stage_timing("historical_dedupe_load", historical_dedupe_started)
            stage_counters["historical_items_loaded"] = len(historical_items)
            stage_counters["contexts_count"] = len(contexts)

            competitor_matching_started = perf_counter()
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

            record_stage_timing("competitor_matching", competitor_matching_started)

            historical_competitor_count_started = perf_counter()
            historical_records = [
                ClusterableRecord(
                    item=item,
                    source_priority=source_priority_map.get(item.source_id, 0),
                    competitor_count=self.repository.load_competitor_match_count(item.normalized_item_id),
                    current_run=False,
                    canonical_event_id=item.canonical_event_id,
                )
                for item in historical_items
            ]
            record_stage_timing("historical_competitor_count_load", historical_competitor_count_started)

            canonical_clustering_started = perf_counter()
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
                historical_records=historical_records,
            )

            record_stage_timing("canonical_clustering", canonical_clustering_started)

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

            canonical_event_writes_started = perf_counter()
            for event_id, assignment in assignments_by_event.items():
                self.repository.upsert_canonical_event(
                    assignment=assignment,
                    members=cluster_result.members_by_event_id[event_id],
                    published_values=cluster_result.published_by_event_id[event_id],
                )

            record_stage_timing("canonical_event_writes", canonical_event_writes_started)

            ranking_rules = load_ranking_rules(self.repo_root / "config" / "ranking_rules.yaml")
            shortlisted_contexts: list[CurrentRunContext] = []

            ranking_and_sent_history_started = perf_counter()
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
                    deployment_match = None
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
                        if funding_match is None:
                            event_flags = context.decision.signals.get("event_flags", {})
                            if not isinstance(event_flags, dict):
                                event_flags = {}
                            semantic_deployment_key = deployment_key_from_text(
                                title=context.item.title,
                                preview=context.item.text_preview,
                                published_ts=context.item.published_ts,
                                event_flags=event_flags,
                            )
                            if semantic_deployment_key is not None:
                                deployment_match = self.repository.find_sent_alert_for_same_deployment_event(
                                    semantic_deployment_key
                                )
                                if deployment_match is not None:
                                    LOGGER.info(
                                        "Cross-run deployment sent-history suppression: item=%s previous_item=%s previous_event=%s previous_url=%s",
                                        context.item.normalized_item_id,
                                        deployment_match["normalized_item_id"],
                                        deployment_match["canonical_event_id"] or "<none>",
                                        deployment_match["canonical_url"],
                                    )
                    context.already_sent = (
                        already_sent_event
                        or already_sent_url
                        or funding_match is not None
                        or deployment_match is not None
                    )
                    if context.already_sent:
                        skip_reason = "already_sent_same_funding_event"
                        if already_sent_event:
                            skip_reason = "already_sent_canonical_event"
                        elif already_sent_url:
                            skip_reason = "already_sent_story_url"
                        elif deployment_match is not None:
                            skip_reason = "already_sent_same_deployment_event"
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
                                "already_sent_same_deployment_event": deployment_match is not None,
                                "already_sent_previous_item_id": (
                                    funding_match["normalized_item_id"]
                                    if funding_match is not None
                                    else (deployment_match["normalized_item_id"] if deployment_match is not None else None)
                                ),
                                "already_sent_previous_event_id": (
                                    funding_match["canonical_event_id"]
                                    if funding_match is not None
                                    else (deployment_match["canonical_event_id"] if deployment_match is not None else None)
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
            stage_counters["shortlisted_count"] = len(shortlisted_contexts)
            record_stage_timing("ranking_and_sent_history", ranking_and_sent_history_started)

            send_threshold = ranking_rules["thresholds"]["send_min_score"]
            summary_generation_started = perf_counter()
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
            record_stage_timing("summary_generation", summary_generation_started)

            if (
                self.settings.radar.claude_editorial_enabled
                and self.claude_editorial_review_client is not None
                and self.claude_editorial_review_client.is_available
            ):
                claude_editorial_contexts = [
                    context
                    for context in contexts
                    if context.decision is not None
                    and context.freshness.is_fresh
                    and context.decision.relevance_status == "keep"
                    and context.decision.send_status != "skip"
                    and (
                        context.decision.is_shortlisted
                        or context.decision.is_borderline
                        or context.decision.score >= max(0, send_threshold - 6)
                    )
                ]
                claude_editorial_contexts.sort(
                    key=_claude_editorial_review_priority,
                    reverse=True,
                )
                claude_editorial_contexts = claude_editorial_contexts[
                    : self.settings.radar.claude_editorial_max_candidates
                ]
                for context in claude_editorial_contexts:
                    if context.summary is None:
                        context.summary = summarize_candidate(context.item, context.decision, self.gemini_client)
                    increment_stage_counter("claude_editorial_attempted")
                    try:
                        claude_result = self.claude_editorial_review_client.review_candidate(
                            title=context.item.title,
                            url=context.item.canonical_url,
                            source=context.source.name,
                            summary=context.summary.summary_text if context.summary else None,
                            score=context.decision.score,
                            ranking_signals=context.decision.signals,
                            freshness=context.freshness.status.value,
                            relevance=context.decision.relevance_status,
                        )
                    except ClaudeEditorialReviewUnavailableError as exc:
                        fallback_reason = record_claude_editorial_fallback(exc.reason)
                        LOGGER.warning(
                            'Claude editorial fallback: reason=%s%s title="%s" source="%s"',
                            fallback_reason,
                            f" status={exc.status_code}" if exc.status_code is not None else "",
                            context.item.title,
                            context.source.name,
                        )
                        continue
                    except Exception as exc:
                        increment_stage_counter("claude_editorial_error")
                        record_claude_editorial_fallback("unknown")
                        LOGGER.warning(
                            'Claude editorial error: reason=unknown title="%s" source="%s" error=%s',
                            context.item.title,
                            context.source.name,
                            type(exc).__name__,
                        )
                        continue

                    if claude_result.is_high_confidence_rejection:
                        increment_stage_counter("claude_editorial_rejected")
                        context.decision = RankedDecision(
                            relevance_status=context.decision.relevance_status,
                            send_status="stored_only",
                            skip_reason="claude_editorial_rejected",
                            score=context.decision.score,
                            signals={
                                **context.decision.signals,
                                "claude_editorial_reject_reason": claude_result.reject_reason,
                                "claude_editorial_confidence": claude_result.confidence,
                            },
                            is_shortlisted=context.decision.is_shortlisted,
                            is_borderline=context.decision.is_borderline,
                        )
                        LOGGER.info(
                            "Claude editorial rejected candidate: item=%s reason=%s",
                            context.item.normalized_item_id,
                            claude_result.reject_reason,
                        )
                        continue

                    if claude_result.is_high_confidence_promotion:
                        increment_stage_counter("claude_editorial_promoted")
                        context.decision = RankedDecision(
                            relevance_status=context.decision.relevance_status,
                            send_status=context.decision.send_status,
                            skip_reason=None,
                            score=context.decision.score,
                            signals={
                                **context.decision.signals,
                                "claude_editorial_promoted": True,
                                "claude_editorial_confidence": claude_result.confidence,
                            },
                            is_shortlisted=context.decision.is_shortlisted,
                            is_borderline=context.decision.is_borderline,
                        )
                        context.final_headline = claude_result.edited_title
                        context.final_summary_text = claude_result.edited_summary
                        _with_context_signals(
                            context,
                            final_card_title_source="claude_editorial_promotion",
                            final_card_summary_source="claude_editorial_promotion",
                        )
                        LOGGER.info(
                            "Claude editorial promoted candidate: item=%s score=%s",
                            context.item.normalized_item_id,
                            context.decision.score,
                        )
                        continue

                    fallback_reason = record_claude_editorial_fallback("low_or_medium_confidence")
                    LOGGER.warning(
                        'Claude editorial fallback: reason=%s confidence=%s title="%s" source="%s"',
                        fallback_reason,
                        claude_result.confidence,
                        context.item.title,
                        context.source.name,
                    )

            editorial_and_late_dedupe_started = perf_counter()
            sendable_candidate_contexts: list[CurrentRunContext] = list(shortlisted_contexts)
            shortlisted_ids = {context.item.normalized_item_id for context in shortlisted_contexts}
            for context in contexts:
                if (
                    context.decision is not None
                    and context.decision.signals.get("claude_editorial_promoted", False)
                    and context.item.normalized_item_id not in shortlisted_ids
                ):
                    sendable_candidate_contexts.append(context)

            sendable_contexts: list[CurrentRunContext] = []
            for context in sendable_candidate_contexts:
                if context.decision.relevance_status != "keep" or context.decision.send_status == "skip":
                    continue

                claude_promoted = bool(context.decision.signals.get("claude_editorial_promoted", False))
                if (
                    not claude_promoted
                    and context.decision.skip_reason == "claude_editorial_rejected"
                ):
                    continue
                if not claude_promoted and context.decision.score < send_threshold:
                    continue

                editorial = evaluate_send_stage_editorial(context.item, context.decision)
                if not editorial.allow_send and not claude_promoted:
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
                    "claude_promoted" if claude_promoted else "eligible",
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
            record_stage_timing("editorial_and_late_dedupe", editorial_and_late_dedupe_started)

            if (
                sendable_contexts
                and self.settings.radar.claude_final_card_enabled
                and self.claude_final_card_client is not None
                and self.claude_final_card_client.is_available
            ):
                claude_contexts = sendable_contexts[: self.settings.radar.claude_final_card_max_candidates]
                filtered_sendable_contexts: list[CurrentRunContext] = []
                for context in sendable_contexts:
                    if context not in claude_contexts:
                        filtered_sendable_contexts.append(context)
                        continue
                    increment_stage_counter("claude_final_card_attempted")
                    try:
                        claude_result = self.claude_final_card_client.generate_final_card(
                            title=context.item.title,
                            source=context.source.name,
                            url=context.item.canonical_url,
                            text_preview=context.item.text_preview,
                            score=context.decision.score,
                            event_flags=context.decision.signals.get("event_flags", {}),
                            signals=context.decision.signals,
                            existing_summary=context.summary.summary_text if context.summary else None,
                        )
                    except ClaudeFinalCardUnavailableError as exc:
                        increment_stage_counter("claude_final_card_fallback")
                        _with_context_signals(
                            context,
                            claude_final_card_reviewed=True,
                            claude_final_card_outcome="fallback_unavailable",
                            claude_final_card_reason=str(exc),
                        )
                        LOGGER.warning(
                            "Claude final-card fallback: item=%s reason=%s",
                            context.item.normalized_item_id,
                            exc,
                        )
                        filtered_sendable_contexts.append(context)
                        continue
                    except Exception as exc:
                        increment_stage_counter("claude_final_card_error")
                        _with_context_signals(
                            context,
                            claude_final_card_reviewed=True,
                            claude_final_card_outcome="fallback_unavailable",
                            claude_final_card_reason=type(exc).__name__,
                        )
                        LOGGER.warning(
                            "Claude final-card error: item=%s reason=%s",
                            context.item.normalized_item_id,
                            exc,
                        )
                        filtered_sendable_contexts.append(context)
                        continue

                    if not claude_result.send_ok:
                        increment_stage_counter("claude_final_card_rejected")
                        context.decision = RankedDecision(
                            relevance_status=context.decision.relevance_status,
                            send_status="stored_only",
                            skip_reason="claude_final_card_rejected",
                            score=context.decision.score,
                            signals={
                                **context.decision.signals,
                                "claude_final_card_reject_reason": claude_result.reject_reason,
                                "claude_final_card_duplicate_risk": claude_result.duplicate_risk,
                                "claude_final_card_confidence": claude_result.confidence,
                            },
                            is_shortlisted=context.decision.is_shortlisted,
                            is_borderline=context.decision.is_borderline,
                        )
                        _with_context_signals(
                            context,
                            claude_final_card_reviewed=True,
                            claude_final_card_outcome="rejected",
                            claude_final_card_reason=claude_result.reject_reason,
                        )
                        LOGGER.info(
                            "Claude final-card rejected candidate: item=%s reason=%s",
                            context.item.normalized_item_id,
                            claude_result.reject_reason or "claude_final_card_rejected",
                        )
                        continue

                    if claude_result.confidence == "low" or not claude_result.title or not claude_result.summary:
                        increment_stage_counter("claude_final_card_fallback")
                        _with_context_signals(
                            context,
                            claude_final_card_reviewed=True,
                            claude_final_card_outcome="fallback_low_confidence",
                            claude_final_card_reason="low_confidence_or_missing_fields",
                        )
                        LOGGER.warning(
                            "Claude final-card fallback: item=%s reason=%s",
                            context.item.normalized_item_id,
                            "low_confidence_or_missing_fields",
                        )
                        filtered_sendable_contexts.append(context)
                        continue

                    context.final_headline = claude_result.title
                    context.final_summary_text = claude_result.summary
                    increment_stage_counter("claude_final_card_used")
                    _with_context_signals(
                        context,
                        claude_final_card_reviewed=True,
                        claude_final_card_outcome="rewritten",
                        claude_final_card_reason=None,
                        final_card_title_source="claude_final_card",
                        final_card_summary_source="claude_final_card",
                    )
                    filtered_sendable_contexts.append(context)
                sendable_contexts = filtered_sendable_contexts

            summary_generation_started = perf_counter()
            for context in contexts:
                if context.summary is None and context.decision and context.decision.is_shortlisted:
                    context.summary = summarize_candidate(context.item, context.decision, self.gemini_client)
            record_stage_timing("summary_generation", summary_generation_started)

            delivery_started = perf_counter()
            for context in sendable_contexts:
                _with_context_signals(context, **_resolve_card_writer_diagnostics(context))
                card = build_news_card(
                    headline=context.final_headline or context.item.title,
                    summary_text=context.final_summary_text or (context.summary.summary_text if context.summary else None),
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

            record_stage_timing("delivery", delivery_started)

            decision_persistence_started = perf_counter()
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

            record_stage_timing("decision_persistence", decision_persistence_started)

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
            run_finalize_and_audit_started = perf_counter()
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
                record_stage_timing("run_finalize_and_audit", run_finalize_and_audit_started)
                report_path = write_run_audit_report(
                    self.repo_root,
                    result,
                    decision_rows,
                    source_audit_rows,
                    round(perf_counter() - run_started, 3),
                    {label: round(duration, 3) for label, duration in stage_timings.items()},
                    stage_counters,
                )
                LOGGER.info("Radar run audit report written: %s", report_path)
            except Exception:
                LOGGER.exception("Failed to write radar run audit report for run_id=%s", run_id)
            LOGGER.info("Radar run complete: %s", format_radar_run_summary(result))
            return result
        except Exception:
            run_finalize_and_audit_started = perf_counter()
            self.repository.finish_pipeline_run(
                run_id,
                PipelineStatus.FAILED,
                {"error": "Radar run failed before completion."},
            )
            raise


def run_radar(repo_root: Path, source_id: str | None = None, dry_run: bool = False) -> RadarRunResult:
    service = RadarService(repo_root=repo_root)
    return service.run(source_id=source_id, dry_run=dry_run)
