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
    FreshnessEvaluation,
    NormalizedItem,
    SourceDefinition,
    StoredNormalizedItem,
)
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
