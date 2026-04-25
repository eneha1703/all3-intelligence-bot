"""Repository abstractions for the first Bot 1 slice."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from all3_radar.domain.enums import PipelineName, PipelineStatus
from all3_radar.domain.models import CollectedRawItem, FreshnessEvaluation, NormalizedItem, SourceDefinition
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
        freshness: FreshnessEvaluation,
        relevance_status: str,
        send_status: str,
        skip_reason: str | None,
        signals: dict[str, Any] | None = None,
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO radar_decisions (
                  normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status,
                  skip_reason, score, signals_json, summary_text, used_gemini, created_at
                )
                VALUES (?, NULL, ?, ?, ?, ?, 0, ?, NULL, 0, ?)
                ON CONFLICT(normalized_item_id) DO UPDATE SET
                  freshness_status=excluded.freshness_status,
                  relevance_status=excluded.relevance_status,
                  send_status=excluded.send_status,
                  skip_reason=excluded.skip_reason,
                  signals_json=excluded.signals_json
                """,
                (
                    normalized_item_id,
                    freshness.status.value,
                    relevance_status,
                    send_status,
                    skip_reason,
                    json.dumps(signals or {"freshness_reason": freshness.reason}, sort_keys=True),
                    _utc_now_iso(),
                ),
            )
            connection.commit()

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
