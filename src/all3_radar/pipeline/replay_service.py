"""Historical replay service for Bot 1 manual validation."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from all3_radar.config.loader import load_settings
from all3_radar.delivery.telegram import TelegramSender, build_news_card, build_replay_card
from all3_radar.domain.enums import PipelineName, PipelineStatus
from all3_radar.domain.models import RadarRunResult, RankedDecision, StoredNormalizedItem
from all3_radar.observability.logging import configure_logging
from all3_radar.observability.run_summary import format_radar_run_summary
from all3_radar.pipeline.editorial import evaluate_send_stage_editorial
from all3_radar.pipeline.ranking import load_ranking_rules, rank_item
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository
from all3_radar.summarization.gemini_client import GeminiClient
from all3_radar.summarization.radar_summary import summarize_candidate

LOGGER = logging.getLogger(__name__)


def _settings_snapshot(settings: object) -> dict[str, Any]:
    snapshot = asdict(settings)
    snapshot["app"]["database_path"] = str(snapshot["app"]["database_path"])
    snapshot["integrations"]["gemini_api_key"] = "***" if snapshot["integrations"]["gemini_api_key"] else None
    snapshot["integrations"]["telegram_alert_bot_token"] = (
        "***" if snapshot["integrations"]["telegram_alert_bot_token"] else None
    )
    return snapshot


class ReplayService:
    def __init__(
        self,
        repo_root: Path,
        repository: RadarRepository | None = None,
        gemini_client: GeminiClient | None = None,
        telegram_sender: TelegramSender | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.settings = load_settings(repo_root)
        configure_logging(self.settings.app.log_level)
        self.repository = repository or RadarRepository(self.settings.app.database_path)
        self.gemini_client = gemini_client or GeminiClient(
            api_key=self.settings.integrations.gemini_api_key,
            model=self.settings.integrations.gemini_model,
        )
        self.telegram_sender = telegram_sender or TelegramSender(
            bot_token=self.settings.integrations.telegram_alert_bot_token,
            chat_ids=self.settings.integrations.telegram_alert_chat_ids,
        )
        initialize_database(self.settings.app.database_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")

    def replay_window(
        self,
        start_date: str,
        end_date: str,
        replay_label: str,
        send: bool = False,
    ) -> RadarRunResult:
        run_id = self.repository.create_pipeline_run(
            PipelineName.RADAR,
            {
                **_settings_snapshot(self.settings),
                "replay": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "label": replay_label,
                    "send": send,
                },
            },
        )
        ranking_rules = load_ranking_rules(self.repo_root / "config" / "ranking_rules.yaml")
        send_threshold = ranking_rules["thresholds"]["send_min_score"]
        items = self.repository.load_items_for_published_window(start_date=start_date, end_date=end_date)

        total_items = len(items)
        shortlisted_count = 0
        sent_count = 0
        skipped_send_count = 0

        try:
            per_event_best: dict[str, tuple[StoredNormalizedItem, RankedDecision]] = {}

            for item in items:
                competitor_count = self.repository.load_competitor_match_count(item.normalized_item_id)
                decision = rank_item(
                    item=item,
                    competitor_count=competitor_count,
                    freshness_is_fresh=True,
                    ranking_rules=ranking_rules,
                )
                if decision.relevance_status != "keep":
                    continue
                event_key = item.canonical_event_id or item.canonical_url or item.normalized_item_id
                existing = per_event_best.get(event_key)
                if existing is None or decision.score > existing[1].score:
                    per_event_best[event_key] = (item, decision)

            replay_candidates: list[tuple[StoredNormalizedItem, RankedDecision]] = []
            for item, decision in sorted(
                per_event_best.values(),
                key=lambda pair: (
                    pair[0].published_ts.isoformat() if pair[0].published_ts else "",
                    pair[1].score,
                ),
            ):
                shortlisted_count += 1
                summary = summarize_candidate(item, decision, self.gemini_client)
                if summary.gemini_decision_override == "drop":
                    skipped_send_count += 1
                    LOGGER.info("Replay gemini drop: item=%s", item.normalized_item_id)
                    continue
                if not (
                    decision.relevance_status == "keep"
                    and decision.score >= send_threshold
                    and decision.send_status != "skip"
                ):
                    continue
                editorial = evaluate_send_stage_editorial(item, decision)
                if not editorial.allow_send:
                    skipped_send_count += 1
                    LOGGER.info(
                        "Replay editorial stored-only: item=%s reason=%s",
                        item.normalized_item_id,
                        editorial.reason,
                    )
                    continue
                card = build_news_card(
                    headline=item.title,
                    summary_text=summary.summary_text,
                    url=item.canonical_url,
                )
                if card is None:
                    skipped_send_count += 1
                    LOGGER.info("Replay skip: item=%s reason=weak_or_empty_telegram_card", item.normalized_item_id)
                    continue
                replay_candidates.append((item, decision))
                if not send:
                    LOGGER.info("Replay dry-run send candidate: item=%s", item.normalized_item_id)
                    continue

                replay_card = build_replay_card(card, replay_label)
                deliveries = self.telegram_sender.send_card(replay_card)
                any_sent = False
                for delivery in deliveries:
                    self.repository.record_telegram_delivery(
                        run_id=run_id,
                        normalized_item_id=item.normalized_item_id,
                        canonical_event_id=item.canonical_event_id or item.normalized_item_id,
                        chat_id=delivery.chat_id,
                        status=delivery.status,
                        payload_text=delivery.payload_text,
                        telegram_message_id=delivery.telegram_message_id,
                        error_text=delivery.error_text,
                        bot_kind="replay",
                    )
                    any_sent = any_sent or delivery.status == "sent"
                    LOGGER.info(
                        "Replay telegram delivery: item=%s status=%s chat_id=%s reason=%s",
                        item.normalized_item_id,
                        delivery.status,
                        delivery.chat_id or "<unset>",
                        delivery.error_text or "ok",
                    )
                if any_sent:
                    sent_count += 1
                else:
                    skipped_send_count += 1

            result = RadarRunResult(
                run_id=run_id,
                selected_sources=0,
                collected_items=0,
                normalized_items=total_items,
                fresh_items=total_items,
                stale_items=0,
                missing_published_ts=0,
                unsupported_sources=0,
                canonical_events=len(per_event_best),
                shortlisted_items=shortlisted_count,
                sent_items=sent_count,
                skipped_send_items=skipped_send_count,
                failed_sources=0,
            )
            self.repository.finish_pipeline_run(
                run_id,
                PipelineStatus.COMPLETED,
                {
                    "replay": True,
                    "start_date": start_date,
                    "end_date": end_date,
                    "label": replay_label,
                    "send": send,
                    "loaded_items": total_items,
                    "unique_events": len(per_event_best),
                    "shortlisted_items": shortlisted_count,
                    "sent_items": sent_count,
                    "skipped_send_items": skipped_send_count,
                },
            )
            LOGGER.info("Replay window complete: %s", format_radar_run_summary(result))
            return result
        except Exception:
            self.repository.finish_pipeline_run(
                run_id,
                PipelineStatus.FAILED,
                {
                    "replay": True,
                    "start_date": start_date,
                    "end_date": end_date,
                    "label": replay_label,
                    "send": send,
                    "error": "Replay failed before completion.",
                },
            )
            raise


def replay_radar_window(
    repo_root: Path,
    start_date: str,
    end_date: str,
    replay_label: str,
    send: bool = False,
) -> RadarRunResult:
    service = ReplayService(repo_root=repo_root)
    return service.replay_window(start_date=start_date, end_date=end_date, replay_label=replay_label, send=send)
