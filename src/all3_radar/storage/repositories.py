"""Repository abstractions for the first Bot 1 slice."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from all3_radar.domain.enums import PipelineName, PipelineStatus
from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import (
    ClusterAssignment,
    CollectedRawItem,
    CompetitorMatch,
    EditorialSignal,
    FreshnessEvaluation,
    NormalizedItem,
    SourceDefinition,
    StoredNormalizedItem,
)
from all3_radar.pipeline.deployment_event_key import (
    DeploymentSemanticKey,
    deployment_key_from_text,
    same_deployment_event,
)
from all3_radar.pipeline.funding_sent_history import FundingSemanticKey, funding_key_from_text, same_funding_event
from all3_radar.storage.db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


class RadarRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def upsert_sources(self, sources: tuple[SourceDefinition, ...]) -> None:
        created_at = _utc_now_iso()
        with connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, base_url, config_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  kind=excluded.kind,
                  layer=excluded.layer,
                  is_direct_source=excluded.is_direct_source,
                  is_wrapper=excluded.is_wrapper,
                  enabled=excluded.enabled,
                  base_url=excluded.base_url,
                  config_json=excluded.config_json
                """,
                [
                    (
                        source.id,
                        source.name,
                        source.kind.value,
                        source.layer.value,
                        int(source.is_direct_source),
                        int(source.is_wrapper),
                        int(source.enabled),
                        source.url,
                        json.dumps(
                            {
                                "parser": source.parser,
                                "priority": source.priority,
                                "tags": list(source.tags),
                                **source.extra_config,
                            },
                            sort_keys=True,
                        ),
                        created_at,
                    )
                    for source in sources
                ],
            )
            connection.commit()

    def create_pipeline_run(self, pipeline: PipelineName, config_snapshot: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO pipeline_runs (id, pipeline, started_at, status, config_snapshot_json, summary_json)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_id,
                    pipeline.value,
                    _utc_now_iso(),
                    PipelineStatus.STARTED.value,
                    json.dumps(config_snapshot, sort_keys=True),
                ),
            )
            connection.commit()
        return run_id

    def finish_pipeline_run(self, run_id: str, status: PipelineStatus, summary: dict[str, Any]) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE pipeline_runs
                SET finished_at = ?, status = ?, summary_json = ?
                WHERE id = ?
                """,
                (_utc_now_iso(), status.value, json.dumps(summary, sort_keys=True), run_id),
            )
            connection.commit()

    def insert_raw_item(self, run_id: str, item: CollectedRawItem) -> str:
        raw_item_id = uuid.uuid4().hex
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO raw_items (
                  id, run_id, source_id, external_id, url, title, snippet, author, published_ts,
                  collected_ts, raw_payload_json, fetch_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_item_id,
                    run_id,
                    item.source_id,
                    item.external_id,
                    item.url,
                    item.title,
                    item.snippet,
                    item.author,
                    _dt_to_iso(item.published_ts),
                    _dt_to_iso(item.collected_ts),
                    json.dumps(item.raw_payload, sort_keys=True),
                    "collected",
                ),
            )
            connection.commit()
        return raw_item_id

    def insert_normalized_item(self, raw_item_id: str, item: NormalizedItem) -> str:
        normalized_item_id = uuid.uuid4().hex
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO normalized_items (
                  id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts,
                  collected_ts, language, layer, is_wrapper, directness_rank, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_item_id,
                    raw_item_id,
                    item.source_id,
                    item.canonical_url,
                    item.domain,
                    item.title,
                    item.dek,
                    item.text_preview,
                    _dt_to_iso(item.published_ts),
                    _dt_to_iso(item.collected_ts),
                    item.language,
                    item.layer.value,
                    int(item.is_wrapper),
                    item.directness_rank,
                    json.dumps(item.metadata, sort_keys=True),
                ),
            )
            connection.commit()
        return normalized_item_id

    def upsert_radar_decision(
        self,
        normalized_item_id: str,
        canonical_event_id: str | None,
        freshness: FreshnessEvaluation,
        relevance_status: str,
        send_status: str,
        skip_reason: str | None,
        score: int = 0,
        signals: dict[str, Any] | None = None,
        summary_text: str | None = None,
        used_gemini: bool = False,
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO radar_decisions (
                  normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status,
                  skip_reason, score, signals_json, summary_text, used_gemini, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_item_id) DO UPDATE SET
                  canonical_event_id=excluded.canonical_event_id,
                  freshness_status=excluded.freshness_status,
                  relevance_status=excluded.relevance_status,
                  send_status=excluded.send_status,
                  skip_reason=excluded.skip_reason,
                  score=excluded.score,
                  signals_json=excluded.signals_json,
                  summary_text=excluded.summary_text,
                  used_gemini=excluded.used_gemini
                """,
                (
                    normalized_item_id,
                    canonical_event_id,
                    freshness.status.value,
                    relevance_status,
                    send_status,
                    skip_reason,
                    score,
                    json.dumps(signals or {"freshness_reason": freshness.reason}, sort_keys=True),
                    summary_text,
                    int(used_gemini),
                    _utc_now_iso(),
                ),
            )
            connection.commit()

    def insert_competitor_matches(self, normalized_item_id: str, matches: list[CompetitorMatch]) -> None:
        if not matches:
            return
        with connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO competitor_matches (normalized_item_id, competitor_name, alias_matched, match_field)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (normalized_item_id, match.competitor_name, match.alias_matched, match.match_field)
                    for match in matches
                ],
            )
            connection.commit()

    def load_recent_items_for_dedupe(self, limit_hours: int = 240) -> list[StoredNormalizedItem]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT ni.id, ni.raw_item_id, ni.source_id, ni.canonical_url, ni.domain, ni.title, ni.text_preview,
                       ni.published_ts, ni.collected_ts, ni.layer, ni.is_wrapper, ni.directness_rank, ni.metadata_json,
                       rd.canonical_event_id
                FROM normalized_items ni
                LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                WHERE julianday(ni.collected_ts) >= julianday('now', ?)
                """,
                (f"-{limit_hours} hours",),
            ).fetchall()
        return [self._row_to_stored_item(row) for row in rows]

    def load_digest_candidates_for_week(
        self,
        start_date: str,
        end_date: str,
        limit: int,
        require_canonical_events: bool,
    ) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            if require_canonical_events:
                rows = connection.execute(
                    """
                    SELECT ce.id AS canonical_event_id,
                           ni.id AS normalized_item_id,
                           ni.source_id,
                           ni.title,
                           ni.canonical_url,
                           ni.published_ts,
                           rd.score,
                           rd.send_status,
                           rd.skip_reason,
                           rd.summary_text,
                           rd.signals_json
                    FROM canonical_events ce
                    JOIN normalized_items ni ON ni.id = ce.representative_item_id
                    JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                    WHERE ce.representative_item_id IS NOT NULL
                      AND rd.relevance_status = 'keep'
                      AND rd.send_status IN ('sent', 'stored_only')
                      AND date(COALESCE(ce.last_published_ts, ni.published_ts)) >= date(?)
                      AND date(COALESCE(ce.last_published_ts, ni.published_ts)) <= date(?)
                    ORDER BY rd.score DESC, COALESCE(ce.last_published_ts, ni.published_ts) DESC, ce.id ASC
                    LIMIT ?
                    """,
                    (start_date, end_date, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT COALESCE(rd.canonical_event_id, ni.id) AS canonical_event_id,
                           ni.id AS normalized_item_id,
                           ni.source_id,
                           ni.title,
                           ni.canonical_url,
                           ni.published_ts,
                           rd.score,
                           rd.send_status,
                           rd.skip_reason,
                           rd.summary_text,
                           rd.signals_json
                    FROM normalized_items ni
                    JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                    WHERE rd.relevance_status = 'keep'
                      AND rd.send_status IN ('sent', 'stored_only')
                      AND ni.published_ts IS NOT NULL
                      AND date(ni.published_ts) >= date(?)
                      AND date(ni.published_ts) <= date(?)
                    ORDER BY rd.score DESC, ni.published_ts DESC, ni.id ASC
                    LIMIT ?
                    """,
                    (start_date, end_date, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def load_telegram_sent_digest_candidates_for_week(
        self,
        *,
        start_date: str,
        end_date: str,
        chat_ids: tuple[str, ...],
        limit: int,
        require_canonical_events: bool,
    ) -> list[dict[str, Any]]:
        if not chat_ids:
            return []
        placeholders = ",".join("?" for _ in chat_ids)
        with connect(self.database_path) as connection:
            if require_canonical_events:
                rows = connection.execute(
                    f"""
                    WITH delivered AS (
                        SELECT COALESCE(td.canonical_event_id, rd.canonical_event_id) AS canonical_event_id,
                               MAX(td.created_at) AS last_sent_at
                        FROM telegram_deliveries td
                        JOIN radar_decisions rd
                          ON rd.normalized_item_id = td.normalized_item_id
                        WHERE td.bot_kind = 'alert'
                          AND td.status = 'sent'
                          AND td.chat_id IN ({placeholders})
                          AND date(td.created_at) >= date(?)
                          AND date(td.created_at) <= date(?)
                          AND COALESCE(td.canonical_event_id, rd.canonical_event_id) IS NOT NULL
                        GROUP BY COALESCE(td.canonical_event_id, rd.canonical_event_id)
                    )
                    SELECT ce.id AS canonical_event_id,
                           ni.id AS normalized_item_id,
                           ni.source_id,
                           ni.title,
                           ni.canonical_url,
                           ni.published_ts,
                           rd.score,
                           'sent' AS send_status,
                           rd.skip_reason,
                           rd.summary_text,
                           rd.signals_json
                    FROM delivered d
                    JOIN canonical_events ce
                      ON ce.id = d.canonical_event_id
                    JOIN normalized_items ni
                      ON ni.id = ce.representative_item_id
                    JOIN radar_decisions rd
                      ON rd.normalized_item_id = ni.id
                    WHERE ce.representative_item_id IS NOT NULL
                      AND rd.relevance_status = 'keep'
                    ORDER BY d.last_sent_at DESC, rd.score DESC, ni.title ASC
                    LIMIT ?
                    """,
                    (*chat_ids, start_date, end_date, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    WITH delivered AS (
                        SELECT COALESCE(td.canonical_event_id, rd.canonical_event_id, td.normalized_item_id) AS candidate_key,
                               MAX(td.created_at) AS last_sent_at,
                               MAX(td.normalized_item_id) AS normalized_item_id
                        FROM telegram_deliveries td
                        JOIN radar_decisions rd
                          ON rd.normalized_item_id = td.normalized_item_id
                        WHERE td.bot_kind = 'alert'
                          AND td.status = 'sent'
                          AND td.chat_id IN ({placeholders})
                          AND date(td.created_at) >= date(?)
                          AND date(td.created_at) <= date(?)
                        GROUP BY COALESCE(td.canonical_event_id, rd.canonical_event_id, td.normalized_item_id)
                    )
                    SELECT COALESCE(rd.canonical_event_id, ni.id) AS canonical_event_id,
                           ni.id AS normalized_item_id,
                           ni.source_id,
                           ni.title,
                           ni.canonical_url,
                           ni.published_ts,
                           rd.score,
                           'sent' AS send_status,
                           rd.skip_reason,
                           rd.summary_text,
                           rd.signals_json
                    FROM delivered d
                    JOIN normalized_items ni
                      ON ni.id = d.normalized_item_id
                    JOIN radar_decisions rd
                      ON rd.normalized_item_id = ni.id
                    WHERE rd.relevance_status = 'keep'
                    ORDER BY d.last_sent_at DESC, rd.score DESC, ni.title ASC
                    LIMIT ?
                    """,
                    (*chat_ids, start_date, end_date, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def upsert_canonical_event(self, assignment: ClusterAssignment, members: list[str], published_values: list[datetime | None]) -> None:
        first_published = min((value for value in published_values if value is not None), default=None)
        last_published = max((value for value in published_values if value is not None), default=None)
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO canonical_events (
                  id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  representative_item_id=excluded.representative_item_id,
                  event_key=excluded.event_key,
                  cluster_title=excluded.cluster_title,
                  first_published_ts=excluded.first_published_ts,
                  last_published_ts=excluded.last_published_ts,
                  updated_at=excluded.updated_at
                """,
                (
                    assignment.canonical_event_id,
                    assignment.representative_item_id,
                    assignment.event_key,
                    assignment.cluster_title,
                    _dt_to_iso(first_published),
                    _dt_to_iso(last_published),
                    _utc_now_iso(),
                    _utc_now_iso(),
                ),
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO event_members (canonical_event_id, normalized_item_id, is_representative)
                VALUES (?, ?, ?)
                """,
                [
                    (
                        assignment.canonical_event_id,
                        member_id,
                        int(member_id == assignment.representative_item_id),
                    )
                    for member_id in members
                ],
            )
            connection.commit()

    def create_weekly_digest_run(self, pipeline_run_id: str, week_key: str) -> str:
        digest_run_id = uuid.uuid4().hex
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO weekly_digest_runs (id, pipeline_run_id, week_key, started_at, status, shortlist_json, final_digest_markdown, final_digest_html)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    digest_run_id,
                    pipeline_run_id,
                    week_key,
                    _utc_now_iso(),
                    PipelineStatus.STARTED.value,
                ),
            )
            connection.commit()
        return digest_run_id

    def replace_weekly_digest_candidates(self, digest_run_id: str, candidates: list[dict[str, Any]]) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                "DELETE FROM weekly_digest_candidates WHERE digest_run_id = ?",
                (digest_run_id,),
            )
            connection.executemany(
                """
                INSERT INTO weekly_digest_candidates (digest_run_id, canonical_event_id, score, rationale_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        digest_run_id,
                        str(candidate["canonical_event_id"]),
                        int(candidate["score"]),
                        json.dumps(
                            {
                                "title": candidate["title"],
                                "source_id": candidate["source_id"],
                                "canonical_url": candidate["canonical_url"],
                                "published_ts": candidate["published_ts"],
                            },
                            sort_keys=True,
                        ),
                    )
                    for candidate in candidates
                ],
            )
            connection.commit()

    def upsert_manual_digest_override_candidate(
        self,
        *,
        item_id: str,
        source_id: str,
        source_name: str,
        canonical_url: str,
        title: str,
        summary_text: str | None,
        published_ts: str | None,
        score: int,
        signals_json: str,
    ) -> None:
        now = _utc_now_iso()
        raw_item_id = f"raw-{item_id}"
        pipeline_run_id = f"manual-digest-override-run-{item_id}"
        domain = canonical_url.split("/")[2].lower() if "://" in canonical_url else "manual.override"
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, base_url, config_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  enabled=excluded.enabled,
                  base_url=excluded.base_url,
                  config_json=excluded.config_json
                """,
                (
                    source_id,
                    source_name,
                    "manual",
                    SourceLayer.DIRECT.value,
                    1,
                    0,
                    1,
                    canonical_url,
                    "{}",
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO pipeline_runs (id, pipeline, started_at, finished_at, status, config_snapshot_json, summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  finished_at=excluded.finished_at,
                  status=excluded.status
                """,
                (
                    pipeline_run_id,
                    PipelineName.DIGEST.value,
                    now,
                    now,
                    PipelineStatus.COMPLETED.value,
                    "{}",
                    "{}",
                ),
            )
            connection.execute(
                """
                INSERT INTO raw_items (id, run_id, source_id, external_id, url, title, snippet, author, published_ts, collected_ts, raw_payload_json, fetch_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  url=excluded.url,
                  title=excluded.title,
                  snippet=excluded.snippet,
                  published_ts=excluded.published_ts,
                  collected_ts=excluded.collected_ts,
                  raw_payload_json=excluded.raw_payload_json,
                  fetch_status=excluded.fetch_status
                """,
                (
                    raw_item_id,
                    pipeline_run_id,
                    source_id,
                    item_id,
                    canonical_url,
                    title,
                    summary_text,
                    None,
                    published_ts,
                    now,
                    "{}",
                    "manual_override",
                ),
            )
            connection.execute(
                """
                INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  source_id=excluded.source_id,
                  canonical_url=excluded.canonical_url,
                  domain=excluded.domain,
                  title=excluded.title,
                  text_preview=excluded.text_preview,
                  published_ts=excluded.published_ts,
                  collected_ts=excluded.collected_ts,
                  metadata_json=excluded.metadata_json
                """,
                (
                    item_id,
                    raw_item_id,
                    source_id,
                    canonical_url,
                    domain,
                    title,
                    None,
                    summary_text,
                    published_ts,
                    now,
                    "en",
                    SourceLayer.DIRECT.value,
                    0,
                    100,
                    "{}",
                ),
            )
            connection.execute(
                """
                INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  representative_item_id=excluded.representative_item_id,
                  cluster_title=excluded.cluster_title,
                  first_published_ts=excluded.first_published_ts,
                  last_published_ts=excluded.last_published_ts,
                  updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    item_id,
                    item_id,
                    title,
                    published_ts,
                    published_ts,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO event_members (canonical_event_id, normalized_item_id, is_representative)
                VALUES (?, ?, ?)
                """,
                (item_id, item_id, 1),
            )
            connection.execute(
                """
                INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_item_id) DO UPDATE SET
                  canonical_event_id=excluded.canonical_event_id,
                  relevance_status=excluded.relevance_status,
                  send_status=excluded.send_status,
                  score=excluded.score,
                  signals_json=excluded.signals_json,
                  summary_text=excluded.summary_text
                """,
                (
                    item_id,
                    item_id,
                    "fresh",
                    "keep",
                    "manual_override",
                    None,
                    score,
                    signals_json,
                    summary_text,
                    0,
                    now,
                ),
            )
            connection.commit()

    def finish_weekly_digest_run(
        self,
        digest_run_id: str,
        status: PipelineStatus,
        shortlist_json: str | None,
        final_digest_markdown: str | None,
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE weekly_digest_runs
                SET finished_at = ?, status = ?, shortlist_json = ?, final_digest_markdown = ?, final_digest_html = NULL
                WHERE id = ?
                """,
                (
                    _utc_now_iso(),
                    status.value,
                    shortlist_json,
                    final_digest_markdown,
                    digest_run_id,
                ),
            )
            connection.commit()

    def has_sent_alert_for_event(self, canonical_event_id: str) -> bool:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM telegram_deliveries
                WHERE canonical_event_id = ? AND bot_kind = 'alert' AND status = 'sent'
                LIMIT 1
                """,
                (canonical_event_id,),
            ).fetchone()
        return bool(row)

    def has_sent_alert_for_url(self, canonical_url: str) -> bool:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM telegram_deliveries td
                JOIN normalized_items ni ON ni.id = td.normalized_item_id
                WHERE ni.canonical_url = ? AND td.bot_kind = 'alert' AND td.status = 'sent'
                LIMIT 1
                """,
                (canonical_url,),
            ).fetchone()
        return bool(row)

    def load_recent_sent_alert_candidates(self, *, lookback_days: int = 7, limit: int = 200) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                  td.normalized_item_id,
                  ni.canonical_url,
                  ni.title,
                  ni.text_preview,
                  ni.published_ts,
                  rd.score,
                  rd.signals_json
                FROM telegram_deliveries td
                JOIN normalized_items ni ON ni.id = td.normalized_item_id
                LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                WHERE td.bot_kind = 'alert'
                  AND td.status = 'sent'
                  AND td.created_at >= datetime('now', ?)
                ORDER BY td.created_at DESC, ni.published_ts DESC, ni.id ASC
                LIMIT ?
                """,
                (f"-{lookback_days} days", limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_sent_alert_for_same_funding_event(self, semantic_key: FundingSemanticKey) -> dict[str, Any] | None:
        start_date = semantic_key.published_date.isoformat()
        end_date = semantic_key.published_date.isoformat()
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT td.normalized_item_id,
                       td.canonical_event_id,
                       td.created_at AS sent_at,
                       ni.canonical_url,
                       ni.title,
                       ni.text_preview,
                       ni.published_ts,
                       ri.url AS raw_url,
                       rd.signals_json
                FROM telegram_deliveries td
                JOIN normalized_items ni ON ni.id = td.normalized_item_id
                LEFT JOIN raw_items ri ON ri.id = ni.raw_item_id
                LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                WHERE td.bot_kind = 'alert'
                  AND td.status = 'sent'
                  AND ni.published_ts IS NOT NULL
                  AND date(ni.published_ts) >= date(?, '-3 days')
                  AND date(ni.published_ts) <= date(?, '+3 days')
                ORDER BY td.created_at DESC, ni.published_ts DESC, td.normalized_item_id ASC
                """,
                (start_date, end_date),
            ).fetchall()

        for row in rows:
            signals = json.loads(row["signals_json"] or "{}")
            event_flags = signals.get("event_flags", {})
            if not isinstance(event_flags, dict):
                event_flags = {}
            previous_key = funding_key_from_text(
                title=str(row["title"]),
                preview=str(row["text_preview"]) if row["text_preview"] else None,
                published_ts=datetime.fromisoformat(str(row["published_ts"])) if row["published_ts"] else None,
                event_flags=event_flags,
            )
            if previous_key is None:
                continue
            if same_funding_event(semantic_key, previous_key):
                return {
                    "normalized_item_id": str(row["normalized_item_id"]),
                    "canonical_event_id": str(row["canonical_event_id"]) if row["canonical_event_id"] else None,
                    "canonical_url": str(row["canonical_url"]),
                    "raw_url": str(row["raw_url"]) if row["raw_url"] else None,
                    "title": str(row["title"]),
                    "published_ts": str(row["published_ts"]),
                    "sent_at": str(row["sent_at"]),
                }
        return None

    def find_sent_alert_for_same_deployment_event(self, semantic_key: DeploymentSemanticKey) -> dict[str, Any] | None:
        start_date = semantic_key.published_date.isoformat()
        end_date = semantic_key.published_date.isoformat()
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT td.normalized_item_id,
                       td.canonical_event_id,
                       td.created_at AS sent_at,
                       ni.canonical_url,
                       ni.title,
                       ni.text_preview,
                       ni.published_ts,
                       ri.url AS raw_url,
                       rd.signals_json
                FROM telegram_deliveries td
                JOIN normalized_items ni ON ni.id = td.normalized_item_id
                LEFT JOIN raw_items ri ON ri.id = ni.raw_item_id
                LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                WHERE td.bot_kind = 'alert'
                  AND td.status = 'sent'
                  AND ni.published_ts IS NOT NULL
                  AND date(ni.published_ts) >= date(?, '-7 days')
                  AND date(ni.published_ts) <= date(?, '+7 days')
                ORDER BY td.created_at DESC, ni.published_ts DESC, td.normalized_item_id ASC
                """,
                (start_date, end_date),
            ).fetchall()

        for row in rows:
            signals = json.loads(row["signals_json"] or "{}")
            event_flags = signals.get("event_flags", {})
            if not isinstance(event_flags, dict):
                event_flags = {}
            previous_key = deployment_key_from_text(
                title=str(row["title"]),
                preview=str(row["text_preview"]) if row["text_preview"] else None,
                published_ts=datetime.fromisoformat(str(row["published_ts"])) if row["published_ts"] else None,
                event_flags=event_flags,
            )
            if previous_key is None:
                continue
            if same_deployment_event(semantic_key, previous_key):
                return {
                    "normalized_item_id": str(row["normalized_item_id"]),
                    "canonical_event_id": str(row["canonical_event_id"]) if row["canonical_event_id"] else None,
                    "canonical_url": str(row["canonical_url"]),
                    "raw_url": str(row["raw_url"]) if row["raw_url"] else None,
                    "title": str(row["title"]),
                    "published_ts": str(row["published_ts"]),
                    "sent_at": str(row["sent_at"]),
                }
        return None

    def load_items_for_published_window(self, start_date: str, end_date: str) -> list[StoredNormalizedItem]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT ni.id, ni.raw_item_id, ni.source_id, ni.canonical_url, ni.domain, ni.title, ni.text_preview,
                       ni.published_ts, ni.collected_ts, ni.layer, ni.is_wrapper, ni.directness_rank, ni.metadata_json,
                       rd.canonical_event_id
                FROM normalized_items ni
                LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                WHERE ni.published_ts IS NOT NULL
                  AND date(ni.published_ts) >= date(?)
                  AND date(ni.published_ts) <= date(?)
                ORDER BY ni.published_ts ASC, ni.id ASC
                """,
                (start_date, end_date),
            ).fetchall()
        return [self._row_to_stored_item(row) for row in rows]

    def load_raw_urls_for_items(self, normalized_item_ids: list[str]) -> dict[str, str]:
        if not normalized_item_ids:
            return {}
        placeholders = ",".join("?" for _ in normalized_item_ids)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT ni.id AS normalized_item_id, ri.url AS raw_url
                FROM normalized_items ni
                JOIN raw_items ri ON ri.id = ni.raw_item_id
                WHERE ni.id IN ({placeholders})
                """,
                tuple(normalized_item_ids),
            ).fetchall()
        return {str(row["normalized_item_id"]): str(row["raw_url"]) for row in rows if row["raw_url"]}

    def record_telegram_delivery(
        self,
        run_id: str,
        normalized_item_id: str,
        canonical_event_id: str,
        chat_id: str,
        status: str,
        payload_text: str,
        telegram_message_id: str | None,
        error_text: str | None,
        bot_kind: str = "alert",
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO telegram_deliveries (
                  id, bot_kind, run_id, normalized_item_id, canonical_event_id, chat_id, telegram_message_id,
                  status, payload_text, error_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    bot_kind,
                    run_id,
                    normalized_item_id,
                    canonical_event_id,
                    chat_id,
                    telegram_message_id,
                    status,
                    payload_text,
                    error_text,
                    _utc_now_iso(),
                ),
            )
            connection.commit()

    def upsert_telegram_group_message(
        self,
        *,
        chat_id: str,
        telegram_message_id: str,
        sent_by_bot: bool,
        sender_user_id: str,
        sender_chat_id: str,
        message_ts: str,
        message_text: str | None,
        message_caption: str | None,
        message_urls: tuple[str, ...],
        has_links: bool,
        normalized_item_id: str | None = None,
        canonical_event_id: str | None = None,
        raw_update: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now_iso()
        single_message_url = message_urls[0] if len(message_urls) == 1 else None
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO telegram_group_messages (
                  id, chat_id, telegram_message_id, sent_by_bot, sender_user_id, sender_chat_id,
                  message_ts, message_text, message_caption, message_url, has_links, link_count,
                  normalized_item_id, canonical_event_id, raw_update_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, telegram_message_id) DO UPDATE SET
                  sent_by_bot=excluded.sent_by_bot,
                  sender_user_id=excluded.sender_user_id,
                  sender_chat_id=excluded.sender_chat_id,
                  message_ts=excluded.message_ts,
                  message_text=excluded.message_text,
                  message_caption=excluded.message_caption,
                  message_url=excluded.message_url,
                  has_links=excluded.has_links,
                  link_count=excluded.link_count,
                  normalized_item_id=COALESCE(excluded.normalized_item_id, telegram_group_messages.normalized_item_id),
                  canonical_event_id=COALESCE(excluded.canonical_event_id, telegram_group_messages.canonical_event_id),
                  raw_update_json=excluded.raw_update_json,
                  updated_at=excluded.updated_at
                """,
                (
                    uuid.uuid4().hex,
                    chat_id,
                    telegram_message_id,
                    int(sent_by_bot),
                    sender_user_id,
                    sender_chat_id,
                    message_ts,
                    message_text,
                    message_caption,
                    single_message_url,
                    int(has_links),
                    len(message_urls),
                    normalized_item_id,
                    canonical_event_id,
                    json.dumps(raw_update or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                DELETE FROM telegram_group_message_links
                WHERE chat_id = ? AND telegram_message_id = ?
                """,
                (chat_id, telegram_message_id),
            )
            for index, url in enumerate(message_urls):
                connection.execute(
                    """
                    INSERT INTO telegram_group_message_links (
                      id, chat_id, telegram_message_id, link_index, url, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, chat_id, telegram_message_id, index, url, now),
                )
            connection.commit()

    def upsert_telegram_reaction_pick(
        self,
        *,
        chat_id: str,
        telegram_message_id: str,
        reactor_user_id: str,
        actor_chat_id: str,
        reaction_key: str,
        is_active: bool,
        picked_at: str,
        source_update_kind: str,
        raw_update: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO telegram_reaction_picks (
                  id, chat_id, telegram_message_id, reactor_user_id, actor_chat_id, reaction_key,
                  is_active, picked_at, source_update_kind, raw_update_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, telegram_message_id, reactor_user_id, actor_chat_id, reaction_key) DO UPDATE SET
                  is_active=excluded.is_active,
                  picked_at=excluded.picked_at,
                  source_update_kind=excluded.source_update_kind,
                  raw_update_json=excluded.raw_update_json,
                  updated_at=excluded.updated_at
                """,
                (
                    uuid.uuid4().hex,
                    chat_id,
                    telegram_message_id,
                    reactor_user_id,
                    actor_chat_id,
                    reaction_key,
                    int(is_active),
                    picked_at,
                    source_update_kind,
                    json.dumps(raw_update or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            connection.commit()

    def load_telegram_reaction_shortlist_candidates(
        self,
        *,
        window_start: str,
        window_end: str,
        allowed_reaction_keys: tuple[str, ...],
        min_unique_reactors: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not allowed_reaction_keys:
            return []
        placeholders = ",".join("?" for _ in allowed_reaction_keys)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT gm.chat_id,
                       gm.telegram_message_id,
                       gm.sent_by_bot,
                       gm.sender_user_id,
                       gm.message_ts,
                       gm.message_text,
                       gm.message_caption,
                       gm.message_url,
                       gm.has_links,
                       gm.normalized_item_id,
                       gm.canonical_event_id,
                       COUNT(DISTINCT NULLIF(COALESCE(NULLIF(rp.reactor_user_id, ''), rp.actor_chat_id), '')) AS unique_reactors,
                       MAX(rp.picked_at) AS last_picked_at
                FROM telegram_reaction_picks rp
                JOIN telegram_group_messages gm
                  ON gm.chat_id = rp.chat_id
                 AND gm.telegram_message_id = rp.telegram_message_id
                WHERE rp.is_active = 1
                  AND rp.reaction_key IN ({placeholders})
                  AND rp.picked_at >= ?
                  AND rp.picked_at <= ?
                  AND ((gm.link_count = 1 AND gm.message_url IS NOT NULL) OR gm.normalized_item_id IS NOT NULL)
                GROUP BY gm.chat_id, gm.telegram_message_id
                HAVING unique_reactors >= ?
                ORDER BY last_picked_at DESC, gm.message_ts DESC
                LIMIT ?
                """,
                (*allowed_reaction_keys, window_start, window_end, min_unique_reactors, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_telegram_reaction_digest_candidates_for_week(
        self,
        *,
        start_date: str,
        end_date: str,
        allowed_reaction_keys: tuple[str, ...],
        min_unique_reactors: int,
        limit: int,
        require_canonical_events: bool,
    ) -> list[dict[str, Any]]:
        if not allowed_reaction_keys:
            return []
        placeholders = ",".join("?" for _ in allowed_reaction_keys)
        canonical_event_expression = (
            "ce.id"
            if require_canonical_events
            else "COALESCE(rd.canonical_event_id, td.canonical_event_id, gm.canonical_event_id, ni.id)"
        )
        canonical_join = (
            "JOIN canonical_events ce ON ce.id = COALESCE(rd.canonical_event_id, td.canonical_event_id, gm.canonical_event_id)"
            if require_canonical_events
            else ""
        )
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                WITH unique_url_matches AS (
                    SELECT ni.canonical_url AS canonical_url,
                           MAX(COALESCE(ce.representative_item_id, ni.id)) AS normalized_item_id
                    FROM normalized_items ni
                    JOIN radar_decisions rd
                      ON rd.normalized_item_id = ni.id
                    LEFT JOIN canonical_events ce
                      ON ce.id = rd.canonical_event_id
                    WHERE rd.relevance_status = 'keep'
                      AND rd.send_status IN ('sent', 'stored_only')
                    GROUP BY ni.canonical_url
                    HAVING COUNT(DISTINCT COALESCE(rd.canonical_event_id, ni.id)) = 1
                )
                SELECT {canonical_event_expression} AS canonical_event_id,
                       ni.id AS normalized_item_id,
                       ni.source_id,
                       ni.title,
                       ni.canonical_url,
                       ni.published_ts,
                       rd.score,
                       rd.send_status,
                       rd.summary_text,
                       rd.signals_json,
                       COUNT(DISTINCT NULLIF(COALESCE(NULLIF(rp.reactor_user_id, ''), rp.actor_chat_id), '')) AS unique_reactors,
                       MAX(rp.picked_at) AS last_picked_at
                FROM telegram_reaction_picks rp
                LEFT JOIN telegram_group_messages gm
                  ON gm.chat_id = rp.chat_id
                 AND gm.telegram_message_id = rp.telegram_message_id
                LEFT JOIN telegram_deliveries td
                  ON td.chat_id = rp.chat_id
                 AND td.telegram_message_id = rp.telegram_message_id
                 AND td.status = 'sent'
                LEFT JOIN normalized_items ni_from_id
                  ON ni_from_id.id = COALESCE(gm.normalized_item_id, td.normalized_item_id)
                LEFT JOIN unique_url_matches url_match
                  ON gm.link_count = 1
                 AND gm.message_url IS NOT NULL
                 AND url_match.canonical_url = gm.message_url
                JOIN normalized_items ni
                  ON ni.id = COALESCE(ni_from_id.id, url_match.normalized_item_id)
                JOIN radar_decisions rd
                  ON rd.normalized_item_id = ni.id
                {canonical_join}
                WHERE rp.is_active = 1
                  AND rp.reaction_key IN ({placeholders})
                  AND date(rp.picked_at) >= date(?)
                  AND date(rp.picked_at) <= date(?)
                  AND rd.relevance_status = 'keep'
                  AND rd.send_status IN ('sent', 'stored_only')
                GROUP BY {canonical_event_expression}, ni.id
                HAVING unique_reactors >= ?
                ORDER BY last_picked_at DESC, rd.score DESC, ni.published_ts DESC
                LIMIT ?
                """,
                (*allowed_reaction_keys, start_date, end_date, min_unique_reactors, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_editorial_signal(self, signal: EditorialSignal) -> None:
        signal_id = uuid.uuid4().hex
        now = _utc_now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO editorial_signals (
                  id, signal_type, signal_state, source_kind, normalized_item_id, canonical_event_id,
                  chat_id, telegram_message_id, user_id, username, raw_value, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_type, source_kind, normalized_item_id, chat_id, user_id) DO UPDATE SET
                  signal_state=excluded.signal_state,
                  canonical_event_id=excluded.canonical_event_id,
                  telegram_message_id=excluded.telegram_message_id,
                  username=excluded.username,
                  raw_value=excluded.raw_value,
                  updated_at=excluded.updated_at
                """,
                (
                    signal_id,
                    signal.signal_type,
                    signal.signal_state,
                    signal.source_kind,
                    signal.normalized_item_id,
                    signal.canonical_event_id,
                    signal.chat_id,
                    signal.telegram_message_id,
                    signal.user_id,
                    signal.username,
                    signal.raw_value,
                    now,
                    now,
                ),
            )
            connection.commit()

    def load_active_shortlist_candidates_for_week(
        self,
        start_date: str,
        end_date: str,
        limit: int,
        require_canonical_events: bool,
    ) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            if require_canonical_events:
                rows = connection.execute(
                    """
                    SELECT ce.id AS canonical_event_id,
                           ni.id AS normalized_item_id,
                           ni.source_id,
                           ni.title,
                           ni.canonical_url,
                           ni.published_ts,
                           rd.score,
                           rd.send_status,
                           rd.summary_text,
                           rd.signals_json
                    FROM editorial_signals es
                    JOIN normalized_items ni ON ni.id = es.normalized_item_id
                    JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                    LEFT JOIN canonical_events ce ON ce.id = rd.canonical_event_id
                    WHERE es.signal_type = 'shortlist'
                      AND es.signal_state = 'active'
                      AND rd.relevance_status = 'keep'
                      AND rd.send_status IN ('sent', 'stored_only')
                      AND ni.published_ts IS NOT NULL
                      AND date(COALESCE(ce.last_published_ts, ni.published_ts)) >= date(?)
                      AND date(COALESCE(ce.last_published_ts, ni.published_ts)) <= date(?)
                    ORDER BY es.updated_at DESC, rd.score DESC, COALESCE(ce.last_published_ts, ni.published_ts) DESC
                    LIMIT ?
                    """,
                    (start_date, end_date, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT COALESCE(rd.canonical_event_id, ni.id) AS canonical_event_id,
                           ni.id AS normalized_item_id,
                           ni.source_id,
                           ni.title,
                           ni.canonical_url,
                           ni.published_ts,
                           rd.score,
                           rd.send_status,
                           rd.summary_text,
                           rd.signals_json
                    FROM editorial_signals es
                    JOIN normalized_items ni ON ni.id = es.normalized_item_id
                    JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                    WHERE es.signal_type = 'shortlist'
                      AND es.signal_state = 'active'
                      AND rd.relevance_status = 'keep'
                      AND rd.send_status IN ('sent', 'stored_only')
                      AND ni.published_ts IS NOT NULL
                      AND date(ni.published_ts) >= date(?)
                      AND date(ni.published_ts) <= date(?)
                    ORDER BY es.updated_at DESC, rd.score DESC, ni.published_ts DESC
                    LIMIT ?
                    """,
                    (start_date, end_date, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_editorial_signal_state(
        self,
        *,
        signal_type: str,
        source_kind: str,
        normalized_item_id: str,
        chat_id: str,
        user_id: str,
    ) -> str | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT signal_state
                FROM editorial_signals
                WHERE signal_type = ?
                  AND source_kind = ?
                  AND normalized_item_id = ?
                  AND chat_id = ?
                  AND user_id = ?
                LIMIT 1
                """,
                (signal_type, source_kind, normalized_item_id, chat_id, user_id),
            ).fetchone()
        return str(row["signal_state"]) if row else None

    def get_item_event_mapping(self, normalized_item_id: str) -> dict[str, str | None] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT ni.id AS normalized_item_id, ce.id AS canonical_event_id
                FROM normalized_items ni
                LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                LEFT JOIN canonical_events ce ON ce.id = rd.canonical_event_id
                WHERE ni.id = ?
                LIMIT 1
                """,
                (normalized_item_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "normalized_item_id": str(row["normalized_item_id"]),
            "canonical_event_id": str(row["canonical_event_id"]) if row["canonical_event_id"] else None,
        }

    def get_integration_cursor(self, consumer_key: str) -> str | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT cursor_value
                FROM integration_cursors
                WHERE consumer_key = ?
                LIMIT 1
                """,
                (consumer_key,),
            ).fetchone()
        return str(row["cursor_value"]) if row else None

    def upsert_integration_cursor(self, consumer_key: str, cursor_value: str) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO integration_cursors (consumer_key, cursor_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(consumer_key) DO UPDATE SET
                  cursor_value=excluded.cursor_value,
                  updated_at=excluded.updated_at
                """,
                (consumer_key, cursor_value, _utc_now_iso()),
            )
            connection.commit()

    def load_competitor_match_count(self, normalized_item_id: str) -> int:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT competitor_name) FROM competitor_matches WHERE normalized_item_id = ?",
                (normalized_item_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def _row_to_stored_item(self, row: Any) -> StoredNormalizedItem:
        return StoredNormalizedItem(
            normalized_item_id=row["id"],
            raw_item_id=row["raw_item_id"],
            source_id=row["source_id"],
            canonical_url=row["canonical_url"],
            domain=row["domain"],
            title=row["title"],
            text_preview=row["text_preview"],
            published_ts=datetime.fromisoformat(row["published_ts"]) if row["published_ts"] else None,
            collected_ts=datetime.fromisoformat(row["collected_ts"]),
            layer=SourceLayer(row["layer"]),
            is_wrapper=bool(row["is_wrapper"]),
            directness_rank=int(row["directness_rank"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
            canonical_event_id=row["canonical_event_id"] if "canonical_event_id" in row.keys() else None,
        )

    def fetch_counts_for_run(self, run_id: str) -> dict[str, int]:
        with connect(self.database_path) as connection:
            raw_count = connection.execute("SELECT COUNT(*) FROM raw_items WHERE run_id = ?", (run_id,)).fetchone()[0]
            normalized_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM normalized_items ni
                JOIN raw_items ri ON ri.id = ni.raw_item_id
                WHERE ri.run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
            return {"raw_items": raw_count, "normalized_items": normalized_count}

    def list_radar_decisions_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT rd.freshness_status, rd.relevance_status, rd.send_status, rd.skip_reason
                FROM radar_decisions rd
                JOIN normalized_items ni ON ni.id = rd.normalized_item_id
                JOIN raw_items ri ON ri.id = ni.raw_item_id
                WHERE ri.run_id = ?
                ORDER BY ni.title
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_radar_decision_details_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                  ni.id AS normalized_item_id,
                  ni.title,
                  ni.source_id,
                  ni.canonical_url,
                  ri.url AS raw_url,
                  ni.published_ts,
                  rd.score,
                  rd.freshness_status,
                  rd.relevance_status,
                  rd.send_status,
                  rd.skip_reason,
                  rd.created_at
                FROM radar_decisions rd
                JOIN normalized_items ni ON ni.id = rd.normalized_item_id
                JOIN raw_items ri ON ri.id = ni.raw_item_id
                WHERE ri.run_id = ?
                ORDER BY
                  CASE WHEN rd.send_status = 'sent' THEN 0 ELSE 1 END,
                  COALESCE(rd.score, 0) DESC,
                  ni.title
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_weekly_review_story_rows(
        self,
        *,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                  COALESCE(rd.canonical_event_id, ni.id) AS canonical_event_id,
                  ni.id AS normalized_item_id,
                  ni.source_id,
                  ni.title,
                  ni.canonical_url,
                  ni.published_ts,
                  rd.score,
                  rd.send_status,
                  rd.skip_reason,
                  rd.summary_text,
                  rd.signals_json
                FROM normalized_items ni
                JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
                WHERE rd.relevance_status = 'keep'
                  AND ni.published_ts IS NOT NULL
                  AND date(ni.published_ts) >= date(?)
                  AND date(ni.published_ts) <= date(?)
                ORDER BY
                  CASE
                    WHEN rd.send_status = 'sent' THEN 0
                    WHEN rd.send_status = 'stored_only' THEN 1
                    ELSE 2
                  END,
                  rd.score DESC,
                  ni.published_ts DESC,
                  ni.id ASC
                LIMIT ?
                """,
                (start_date, end_date, limit),
            ).fetchall()
        return [dict(row) for row in rows]
