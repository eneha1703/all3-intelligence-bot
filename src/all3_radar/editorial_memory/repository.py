"""Repository helpers for curated editorial memory evidence."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.editorial_memory.models import EditorialMemoryExample, StoredEditorialMemoryExample
from all3_radar.storage.db import connect, initialize_database


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EditorialMemoryRepository:
    def __init__(self, database_path: Path, schema_path: Path) -> None:
        self.database_path = database_path
        self.schema_path = schema_path

    def initialize(self) -> None:
        initialize_database(self.database_path, self.schema_path)

    def add_example(self, example: EditorialMemoryExample) -> str:
        example_id = uuid.uuid4().hex
        now = _utc_now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO editorial_memory_examples (
                  id, created_at, updated_at, kind, title, feedback_text, source, url, week_key, pipeline_stage,
                  decision_tags_json, linked_rule_ids_json, resolution_status, source_fingerprint, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_fingerprint) DO UPDATE SET
                  updated_at=excluded.updated_at,
                  kind=excluded.kind,
                  title=excluded.title,
                  feedback_text=excluded.feedback_text,
                  source=excluded.source,
                  url=excluded.url,
                  week_key=excluded.week_key,
                  pipeline_stage=excluded.pipeline_stage,
                  decision_tags_json=excluded.decision_tags_json,
                  linked_rule_ids_json=excluded.linked_rule_ids_json,
                  resolution_status=excluded.resolution_status,
                  metadata_json=excluded.metadata_json
                """,
                (
                    example_id,
                    now,
                    now,
                    example.kind,
                    example.title,
                    example.feedback_text,
                    example.source,
                    example.url,
                    example.week_key,
                    example.pipeline_stage,
                    json.dumps(list(example.decision_tags), sort_keys=True),
                    json.dumps(list(example.linked_rule_ids), sort_keys=True),
                    example.resolution_status,
                    example.source_fingerprint,
                    json.dumps(example.metadata or {}, sort_keys=True),
                ),
            )
            connection.commit()
            if example.source_fingerprint:
                row = connection.execute(
                    "SELECT id FROM editorial_memory_examples WHERE source_fingerprint = ?",
                    (example.source_fingerprint,),
                ).fetchone()
                if row:
                    return str(row["id"])
        return example_id

    def list_examples(
        self,
        *,
        kind: str | None = None,
        resolution_status: str | None = None,
        limit: int = 20,
    ) -> list[StoredEditorialMemoryExample]:
        clauses: list[str] = []
        params: list[object] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if resolution_status:
            clauses.append("resolution_status = ?")
            params.append(resolution_status)
        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)
        params.append(limit)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT id, created_at, updated_at, kind, title, feedback_text, source, url, week_key, pipeline_stage,
                       decision_tags_json, linked_rule_ids_json, resolution_status, source_fingerprint, metadata_json
                FROM editorial_memory_examples
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_example(row) for row in rows]

    def summarize(self) -> dict[str, object]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT kind, resolution_status, decision_tags_json
                FROM editorial_memory_examples
                """
            ).fetchall()
        by_kind = Counter[str]()
        by_resolution = Counter[str]()
        tags = Counter[str]()
        for row in rows:
            by_kind.update([str(row["kind"])])
            by_resolution.update([str(row["resolution_status"])])
            tags.update(json.loads(row["decision_tags_json"]))
        return {
            "total_examples": len(rows),
            "by_kind": dict(sorted(by_kind.items())),
            "by_resolution_status": dict(sorted(by_resolution.items())),
            "top_decision_tags": dict(tags.most_common(10)),
        }

    def _row_to_example(self, row: object) -> StoredEditorialMemoryExample:
        return StoredEditorialMemoryExample(
            id=str(row["id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            kind=str(row["kind"]),
            title=str(row["title"]),
            feedback_text=str(row["feedback_text"]),
            source=row["source"],
            url=row["url"],
            week_key=row["week_key"],
            pipeline_stage=row["pipeline_stage"],
            decision_tags=tuple(json.loads(row["decision_tags_json"])),
            linked_rule_ids=tuple(json.loads(row["linked_rule_ids_json"])),
            resolution_status=str(row["resolution_status"]),
            source_fingerprint=row["source_fingerprint"],
            metadata=json.loads(row["metadata_json"]),
        )

