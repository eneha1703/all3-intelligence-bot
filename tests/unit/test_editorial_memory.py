from __future__ import annotations

import json
from pathlib import Path

from all3_radar.editorial_memory.models import EditorialMemoryExample
from all3_radar.editorial_memory.paths import (
    resolve_editorial_memory_database_path,
    resolve_editorial_memory_rules_path,
    resolve_editorial_memory_schema_path,
)
from all3_radar.editorial_memory.repository import EditorialMemoryRepository
from all3_radar.editorial_memory.service import load_digest_example_seed, load_manual_seed_examples, load_presets, load_rules


def test_editorial_memory_repository_stores_and_lists_examples(tmp_path: Path) -> None:
    db_path = tmp_path / "editorial_memory.db"
    schema_path = Path(__file__).resolve().parents[2] / "src" / "all3_radar" / "editorial_memory" / "schema.sql"
    repository = EditorialMemoryRepository(db_path, schema_path)
    repository.initialize()

    example_id = repository.add_example(
        EditorialMemoryExample(
            kind="summary_bad",
            title="Broken summary tail",
            feedback_text="Sentence ends on a dangling phrase and should be rejected.",
            source="manual_review",
            decision_tags=("broken_tail", "summary_quality"),
            linked_rule_ids=("summary_no_broken_tails",),
            resolution_status="accepted",
        )
    )

    rows = repository.list_examples(limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == example_id
    assert row.kind == "summary_bad"
    assert row.decision_tags == ("broken_tail", "summary_quality")
    assert row.linked_rule_ids == ("summary_no_broken_tails",)

    summary = repository.summarize()
    assert summary["total_examples"] == 1
    assert summary["by_kind"] == {"summary_bad": 1}


def test_editorial_memory_seed_examples_upsert_by_fingerprint(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = EditorialMemoryRepository(
        tmp_path / "editorial_memory.db",
        resolve_editorial_memory_schema_path(repo_root),
    )
    repository.initialize()

    seed_examples = load_digest_example_seed(repo_root)
    for example in seed_examples:
        repository.add_example(example)
    for example in seed_examples:
        repository.add_example(example)

    rows = repository.list_examples(limit=20)
    assert len(rows) == len(seed_examples)
    assert any(row.kind == "digest_good" for row in rows)
    assert any(row.kind == "digest_bad" for row in rows)


def test_editorial_memory_rules_file_loads() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload = load_rules(resolve_editorial_memory_rules_path(repo_root))
    rule_ids = {rule["id"] for rule in payload["rules"]}
    assert "digest_human_editor_voice" in rule_ids
    assert "digest_name_pipeline_constraint" in rule_ids
    assert "digest_surface_operational_wedge" in rule_ids
    assert "selection_prefer_high_signal_sector_relevance" in rule_ids


def test_editorial_memory_paths_default_to_repo_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EDITORIAL_MEMORY_DATABASE_PATH", raising=False)
    resolved = resolve_editorial_memory_database_path(tmp_path)
    assert resolved == tmp_path / "data" / "editorial_memory.db"


def test_editorial_memory_presets_file_loads() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload = load_presets(repo_root / "config" / "editorial_memory_presets.yaml")
    preset_keys = set(payload["presets"].keys())
    assert "summary_bad" in preset_keys
    assert "summary_good" in preset_keys


def test_editorial_memory_manual_seed_examples_load() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    examples = load_manual_seed_examples(repo_root)
    assert any(example.title == "Double whammy hits April construction output" for example in examples)
    assert any(example.kind == "summary_bad" for example in examples)
