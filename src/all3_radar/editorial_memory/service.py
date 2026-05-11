"""Service helpers for editorial memory rules and seed examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from all3_radar.config.loader import load_yaml
from all3_radar.editorial_memory.models import EditorialMemoryExample


def load_rules(rules_path: Path) -> dict[str, Any]:
    payload = load_yaml(rules_path)
    if "rules" not in payload:
        raise ValueError(f"Editorial memory rules file is missing 'rules': {rules_path}")
    return payload


def load_presets(presets_path: Path) -> dict[str, Any]:
    payload = load_yaml(presets_path)
    if "presets" not in payload:
        raise ValueError(f"Editorial memory presets file is missing 'presets': {presets_path}")
    return payload


def load_digest_example_seed(repo_root: Path) -> list[EditorialMemoryExample]:
    path = repo_root / "src" / "all3_radar" / "digest" / "weekly_writer_examples.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    examples: list[EditorialMemoryExample] = []
    for idx, item in enumerate(payload):
        label = str(item["label"]).strip().lower()
        kind = "digest_good" if label == "good" else "digest_bad"
        notes = [str(note).strip() for note in item.get("notes", []) if str(note).strip()]
        examples.append(
            EditorialMemoryExample(
                kind=kind,
                title=str(item["headline"]).strip(),
                feedback_text=str(item["body_html"]).strip(),
                source="weekly_writer_examples",
                pipeline_stage="digest_writer",
                decision_tags=tuple(f"digest_example:{label}" for _ in [0]) + tuple(
                    _slugify_note(note) for note in notes
                ),
                linked_rule_ids=_linked_rule_ids_for_label(label),
                resolution_status="accepted",
                source_fingerprint=f"weekly_writer_examples:{label}:{idx}",
                metadata={"notes": notes},
            )
        )
    return examples


def load_manual_seed_examples(repo_root: Path) -> list[EditorialMemoryExample]:
    path = repo_root / "config" / "editorial_memory_seed_examples.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    examples: list[EditorialMemoryExample] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        examples.append(
            EditorialMemoryExample(
                kind=str(item["kind"]).strip(),
                title=str(item["title"]).strip(),
                feedback_text=str(item["feedback_text"]).strip(),
                source=_optional_str(item.get("source")),
                url=_optional_str(item.get("url")),
                week_key=_optional_str(item.get("week_key")),
                pipeline_stage=_optional_str(item.get("pipeline_stage")),
                decision_tags=tuple(str(tag).strip() for tag in item.get("decision_tags", []) if str(tag).strip()),
                linked_rule_ids=tuple(
                    str(rule_id).strip() for rule_id in item.get("linked_rule_ids", []) if str(rule_id).strip()
                ),
                resolution_status=_optional_str(item.get("resolution_status")) or "accepted",
                source_fingerprint=_optional_str(item.get("source_fingerprint")),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            )
        )
    return examples


def _linked_rule_ids_for_label(label: str) -> tuple[str, ...]:
    if label == "good":
        return (
            "digest_human_editor_voice",
            "digest_fact_first",
            "digest_compact_single_paragraph",
        )
    return (
        "digest_avoid_generic_recap",
        "digest_avoid_ai_justification",
        "digest_avoid_redundant_headline_body",
    )


def _slugify_note(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
