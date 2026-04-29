"""Historical replay service for Bot 1 manual validation."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def _normalize_url_key(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip()
    if not normalized:
        return None
    parts = urlsplit(normalized)
    path = parts.path.rstrip("/") if parts.path not in {"", "/"} else parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _load_allowlist_urls(path: Path | None) -> tuple[list[tuple[str, str]], int]:
    if path is None or not path.exists():
        return [], 0

    ordered_urls: list[tuple[str, str]] = []
    seen: set[str] = set()
    duplicate_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        raw_url = line.strip()
        if not raw_url:
            continue
        normalized = _normalize_url_key(raw_url)
        if not normalized:
            continue
        if normalized in seen:
            duplicate_lines += 1
            continue
        seen.add(normalized)
        ordered_urls.append((raw_url, normalized))
    return ordered_urls, duplicate_lines


def _url_representative_sort_key(item: StoredNormalizedItem, score: int) -> tuple[int, str, str]:
    published = item.published_ts.isoformat() if item.published_ts else ""
    stable = item.canonical_url or item.normalized_item_id
    return (score, published, stable)


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
        allowlist_urls_file: Path | None = None,
    ) -> RadarRunResult:
        allowlist_urls, duplicate_allowlist_lines = _load_allowlist_urls(allowlist_urls_file)
        run_id = self.repository.create_pipeline_run(
            PipelineName.RADAR,
            {
                **_settings_snapshot(self.settings),
                "replay": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "label": replay_label,
                    "send": send,
                    "allowlist_urls_file": str(allowlist_urls_file) if allowlist_urls_file else None,
                    "allowlist_url_count": len(allowlist_urls),
                },
            },
        )
        ranking_rules = load_ranking_rules(self.repo_root / "config" / "ranking_rules.yaml")
        send_threshold = ranking_rules["thresholds"]["send_min_score"]
        window_items = self.repository.load_items_for_published_window(start_date=start_date, end_date=end_date)

        total_items = len(window_items)
        shortlisted_count = 0
        sent_count = 0
        skipped_send_count = 0

        try:
            replay_candidates: list[tuple[StoredNormalizedItem, RankedDecision]] = []
            preselected_candidates: list[tuple[StoredNormalizedItem, RankedDecision]] = []
            collapsed_duplicate_url_rows = 0
            missing_allowlist_urls: list[str] = []

            if allowlist_urls:
                raw_urls_by_item = self.repository.load_raw_urls_for_items(
                    [item.normalized_item_id for item in window_items]
                )
                decisions_by_item: dict[str, RankedDecision] = {}
                matched_by_url: dict[str, list[tuple[StoredNormalizedItem, RankedDecision]]] = defaultdict(list)

                for item in window_items:
                    competitor_count = self.repository.load_competitor_match_count(item.normalized_item_id)
                    decision = rank_item(
                        item=item,
                        competitor_count=competitor_count,
                        freshness_is_fresh=True,
                        ranking_rules=ranking_rules,
                    )
                    decisions_by_item[item.normalized_item_id] = decision
                    variant_keys = {
                        key
                        for key in (
                            _normalize_url_key(item.canonical_url),
                            _normalize_url_key(raw_urls_by_item.get(item.normalized_item_id)),
                        )
                        if key
                    }
                    for _, allowlist_key in allowlist_urls:
                        if allowlist_key in variant_keys:
                            matched_by_url[allowlist_key].append((item, decision))

                for original_url, allowlist_key in allowlist_urls:
                    matches = matched_by_url.get(allowlist_key, [])
                    if not matches:
                        missing_allowlist_urls.append(original_url)
                        LOGGER.warning("Replay allowlist URL missing from DB window: url=%s", original_url)
                        continue
                    matches = sorted(
                        matches,
                        key=lambda pair: _url_representative_sort_key(pair[0], pair[1].score),
                        reverse=True,
                    )
                    preselected_candidates.append(matches[0])
                    collapsed_duplicate_url_rows += max(0, len(matches) - 1)

                LOGGER.info(
                    "Replay allowlist selection: requested=%s selected=%s missing=%s duplicate_rows_collapsed=%s duplicate_lines_ignored=%s",
                    len(allowlist_urls),
                    len(preselected_candidates),
                    len(missing_allowlist_urls),
                    collapsed_duplicate_url_rows,
                    duplicate_allowlist_lines,
                )
            else:
                per_event_best: dict[str, tuple[StoredNormalizedItem, RankedDecision]] = {}

                for item in window_items:
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

                preselected_candidates = sorted(
                    per_event_best.values(),
                    key=lambda pair: (
                        pair[0].published_ts.isoformat() if pair[0].published_ts else "",
                        pair[1].score,
                    ),
                )

            for item, decision in preselected_candidates:
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

                replay_card = build_replay_card(card, replay_label) if replay_label.strip() else card
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

            canonical_event_count = (
                len({item.canonical_event_id or item.canonical_url or item.normalized_item_id for item, _ in preselected_candidates})
                if allowlist_urls
                else len(preselected_candidates)
            )

            result = RadarRunResult(
                run_id=run_id,
                selected_sources=0,
                collected_items=0,
                normalized_items=total_items,
                fresh_items=total_items,
                stale_items=0,
                missing_published_ts=0,
                unsupported_sources=0,
                canonical_events=canonical_event_count,
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
                    "unique_events": canonical_event_count,
                    "shortlisted_items": shortlisted_count,
                    "sent_items": sent_count,
                    "skipped_send_items": skipped_send_count,
                    "allowlist_url_count": len(allowlist_urls),
                    "allowlist_missing_urls": missing_allowlist_urls,
                    "allowlist_duplicate_rows_collapsed": collapsed_duplicate_url_rows,
                    "allowlist_duplicate_lines_ignored": duplicate_allowlist_lines,
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
                    "allowlist_url_count": len(allowlist_urls),
                },
            )
            raise


def replay_radar_window(
    repo_root: Path,
    start_date: str,
    end_date: str,
    replay_label: str,
    send: bool = False,
    allowlist_urls_file: Path | None = None,
) -> RadarRunResult:
    service = ReplayService(repo_root=repo_root)
    return service.replay_window(
        start_date=start_date,
        end_date=end_date,
        replay_label=replay_label,
        send=send,
        allowlist_urls_file=allowlist_urls_file,
    )
