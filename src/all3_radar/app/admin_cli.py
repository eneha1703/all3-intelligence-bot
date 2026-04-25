"""Administrative CLI helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from all3_radar.config.loader import load_settings, load_yaml
from all3_radar.sources.registry import load_source_registry
from all3_radar.storage.db import initialize_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administrative commands for All3 radar")
    subparsers = parser.add_subparsers(dest="group", required=True)

    db_parser = subparsers.add_parser("db", help="Database utilities")
    db_subparsers = db_parser.add_subparsers(dest="command", required=True)
    db_subparsers.add_parser("init", help="Initialize the SQLite schema")

    sources_parser = subparsers.add_parser("sources", help="Source inventory utilities")
    sources_subparsers = sources_parser.add_subparsers(dest="command", required=True)
    sources_subparsers.add_parser("list", help="List configured sources")
    show_parser = sources_subparsers.add_parser("show", help="Show one configured source")
    show_parser.add_argument("source_id", help="Source id")

    competitors_parser = subparsers.add_parser("competitors", help="Competitor utilities")
    competitors_subparsers = competitors_parser.add_subparsers(dest="command", required=True)
    competitors_subparsers.add_parser("list", help="List configured competitors")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[3]

    if args.group == "db" and args.command == "init":
        settings = load_settings(repo_root)
        initialize_database(settings.app.database_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
        print(f"Database initialized at {settings.app.database_path}.")
        return 0

    if args.group == "sources" and args.command == "list":
        for source in load_source_registry(repo_root / "config" / "sources.yaml").all():
            print(f"{source.id}: {source.name} [{source.kind.value}, {source.layer.value}]")
        return 0

    if args.group == "sources" and args.command == "show":
        for source in load_source_registry(repo_root / "config" / "sources.yaml").all():
            if source.id == args.source_id:
                print(source)
                return 0
        parser.error(f"Unknown source id: {args.source_id}")

    if args.group == "competitors" and args.command == "list":
        config = load_yaml(repo_root / "config" / "competitors.yaml")
        for company in config["companies"]:
            print(f"{company['canonical']}: {', '.join(company['aliases'])}")
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
