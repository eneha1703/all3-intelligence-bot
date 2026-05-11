"""Typed models for the editorial memory layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EditorialMemoryExample:
    kind: str
    title: str
    feedback_text: str
    source: str | None = None
    url: str | None = None
    week_key: str | None = None
    pipeline_stage: str | None = None
    decision_tags: tuple[str, ...] = ()
    linked_rule_ids: tuple[str, ...] = ()
    resolution_status: str = "accepted"
    source_fingerprint: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class StoredEditorialMemoryExample:
    id: str
    created_at: str
    updated_at: str
    kind: str
    title: str
    feedback_text: str
    source: str | None
    url: str | None
    week_key: str | None
    pipeline_stage: str | None
    decision_tags: tuple[str, ...]
    linked_rule_ids: tuple[str, ...]
    resolution_status: str
    source_fingerprint: str | None
    metadata: dict[str, Any]

