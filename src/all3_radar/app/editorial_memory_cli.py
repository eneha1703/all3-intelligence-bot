"""CLI entry points for the editorial memory layer."""

from __future__ import annotations

import argparse
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Editorial memory tools for All3 radar")
    subparsers = parser.add_subparsers(dest="group", required=True)

    db_parser = subparsers.add_parser("db", help="Editorial memory database utilities")
    db_subparsers = db_parser.add_subparsers(dest="command", required=True)
    db_subparsers.add_parser("init", help="Initialize the editorial memory SQLite schema")

    rules_parser = subparsers.add_parser("rules", help="Stable editorial rules")
    rules_subparsers = rules_parser.add_subparsers(dest="command", required=True)
    rules_subparsers.add_parser("show", help="Print configured editorial memory rules")

    evidence_parser = subparsers.add_parser("evidence", help="Curated examples and feedback")
    evidence_subparsers = evidence_parser.add_subparsers(dest="command", required=True)

    add_parser = evidence_subparsers.add_parser("add", help="Add one curated editorial memory example")
    add_parser.add_argument("--kind", required=True, help="Example kind, for example digest_good or summary_bad")
    add_parser.add_argument("--title", required=True, help="Short label/title for the example")
    add_parser.add_argument("--feedback-text", required=True, help="Why the example matters")
    add_parser.add_argument("--source", default=None, help="Optional source label")
    add_parser.add_argument("--url", default=None, help="Optional canonical URL")
    add_parser.add_argument("--week-key", default=None, help="Optional ISO week key")
    add_parser.add_argument("--pipeline-stage", default=None, help="Optional pipeline stage label")
    add_parser.add_argument("--decision-tag", action="append", default=[], help="Repeatable decision tag")
    add_parser.add_argument("--linked-rule-id", action="append", default=[], help="Repeatable linked rule id")
    add_parser.add_argument("--resolution-status", default="accepted", help="Resolution status")

    quick_add_parser = evidence_subparsers.add_parser(
        "quick-add",
        help="Add one curated example using a preset such as summary_bad or summary_good",
    )
    quick_add_parser.add_argument("--preset", required=True, help="Preset key from editorial_memory_presets.yaml")
    quick_add_parser.add_argument("--title", required=True, help="Short label/title for the example")
    quick_add_parser.add_argument("--feedback-text", required=True, help="Why the example matters")
    quick_add_parser.add_argument("--source", default=None, help="Optional source label override")
    quick_add_parser.add_argument("--url", default=None, help="Optional canonical URL")
    quick_add_parser.add_argument("--week-key", default=None, help="Optional ISO week key")
    quick_add_parser.add_argument("--decision-tag", action="append", default=[], help="Repeatable extra decision tag")
    quick_add_parser.add_argument("--linked-rule-id", action="append", default=[], help="Repeatable extra linked rule id")
    quick_add_parser.add_argument("--resolution-status", default=None, help="Optional resolution status override")

    list_parser = evidence_subparsers.add_parser("list", help="List stored editorial memory examples")
    list_parser.add_argument("--kind", default=None, help="Filter by kind")
    list_parser.add_argument("--resolution-status", default=None, help="Filter by resolution status")
    list_parser.add_argument("--limit", type=int, default=20, help="Maximum rows to print")

    evidence_subparsers.add_parser("summarize", help="Print aggregate counts for stored examples")
    evidence_subparsers.add_parser("seed-digest-examples", help="Import existing digest good/bad examples")
    evidence_subparsers.add_parser("seed-manual-examples", help="Import curated manual seed examples from config")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[3]

    repository = EditorialMemoryRepository(
        resolve_editorial_memory_database_path(repo_root),
        resolve_editorial_memory_schema_path(repo_root),
    )

    if args.group == "db" and args.command == "init":
        repository.initialize()
        print(f"Editorial memory database initialized at {repository.database_path}.")
        return 0

    if args.group == "rules" and args.command == "show":
        payload = load_rules(resolve_editorial_memory_rules_path(repo_root))
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.group == "evidence" and args.command == "add":
        repository.initialize()
        example = EditorialMemoryExample(
            kind=args.kind.strip(),
            title=args.title.strip(),
            feedback_text=args.feedback_text.strip(),
            source=_strip_or_none(args.source),
            url=_strip_or_none(args.url),
            week_key=_strip_or_none(args.week_key),
            pipeline_stage=_strip_or_none(args.pipeline_stage),
            decision_tags=tuple(tag.strip() for tag in args.decision_tag if tag.strip()),
            linked_rule_ids=tuple(rule_id.strip() for rule_id in args.linked_rule_id if rule_id.strip()),
            resolution_status=args.resolution_status.strip() or "accepted",
        )
        example_id = repository.add_example(example)
        print(f"Stored editorial memory example {example_id}.")
        return 0

    if args.group == "evidence" and args.command == "quick-add":
        repository.initialize()
        presets = load_presets(repo_root / "config" / "editorial_memory_presets.yaml")
        preset = presets["presets"].get(args.preset)
        if not isinstance(preset, dict):
            parser.error(f"Unknown editorial memory preset: {args.preset}")
        example = EditorialMemoryExample(
            kind=str(preset["kind"]).strip(),
            title=args.title.strip(),
            feedback_text=args.feedback_text.strip(),
            source=_strip_or_none(args.source) or _strip_or_none(preset.get("source")),
            url=_strip_or_none(args.url),
            week_key=_strip_or_none(args.week_key),
            pipeline_stage=_strip_or_none(preset.get("pipeline_stage")),
            decision_tags=tuple(
                [tag.strip() for tag in preset.get("decision_tags", []) if str(tag).strip()]
                + [tag.strip() for tag in args.decision_tag if tag.strip()]
            ),
            linked_rule_ids=tuple(
                [rule_id.strip() for rule_id in preset.get("linked_rule_ids", []) if str(rule_id).strip()]
                + [rule_id.strip() for rule_id in args.linked_rule_id if rule_id.strip()]
            ),
            resolution_status=_strip_or_none(args.resolution_status)
            or _strip_or_none(preset.get("resolution_status"))
            or "accepted",
        )
        example_id = repository.add_example(example)
        print(f"Stored editorial memory example {example_id} with preset {args.preset}.")
        return 0

    if args.group == "evidence" and args.command == "list":
        repository.initialize()
        rows = repository.list_examples(
            kind=_strip_or_none(args.kind),
            resolution_status=_strip_or_none(args.resolution_status),
            limit=args.limit,
        )
        for row in rows:
            print(
                json.dumps(
                    {
                        "id": row.id,
                        "kind": row.kind,
                        "title": row.title,
                        "resolution_status": row.resolution_status,
                        "decision_tags": list(row.decision_tags),
                        "linked_rule_ids": list(row.linked_rule_ids),
                        "source": row.source,
                        "week_key": row.week_key,
                        "created_at": row.created_at,
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    if args.group == "evidence" and args.command == "summarize":
        repository.initialize()
        print(json.dumps(repository.summarize(), indent=2, ensure_ascii=False))
        return 0

    if args.group == "evidence" and args.command == "seed-digest-examples":
        repository.initialize()
        imported = 0
        for example in load_digest_example_seed(repo_root):
            repository.add_example(example)
            imported += 1
        print(f"Seeded {imported} digest examples into editorial memory.")
        return 0

    if args.group == "evidence" and args.command == "seed-manual-examples":
        repository.initialize()
        imported = 0
        for example in load_manual_seed_examples(repo_root):
            repository.add_example(example)
            imported += 1
        print(f"Seeded {imported} manual examples into editorial memory.")
        return 0

    parser.error("Unknown command")
    return 2


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


if __name__ == "__main__":
    raise SystemExit(main())
