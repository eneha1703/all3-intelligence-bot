"""CLI entry points for the Weekly Digest Bot."""

from __future__ import annotations

import argparse
from pathlib import Path

from all3_radar.digest.digest_service import DigestService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the All3 Weekly Digest Bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    shortlist_parser = subparsers.add_parser("shortlist", help="Create a deterministic weekly shortlist")
    shortlist_parser.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")

    build_parser_cmd = subparsers.add_parser("build", help="Build weekly digest markdown with optional Claude synthesis")
    build_parser_cmd.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")
    build_parser_cmd.add_argument("--output", required=False, help="Optional markdown output path")

    send_parser = subparsers.add_parser("send", help="Send a previously built weekly digest")
    send_parser.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect digest candidates and output")
    inspect_parser.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "shortlist":
        repo_root = Path(__file__).resolve().parents[3]
        service = DigestService(repo_root=repo_root)
        result = service.build_shortlist(args.week)
        print(f"Digest shortlist complete: week={result.week_key} candidates={result.candidate_count}")
        for index, candidate in enumerate(result.candidates, start=1):
            print(
                f"{index}. {candidate.title} | score={candidate.score} | source={candidate.source_id} | "
                f"url={candidate.canonical_url}"
            )
        return 0

    if args.command == "build":
        repo_root = Path(__file__).resolve().parents[3]
        service = DigestService(repo_root=repo_root)
        result = service.build_digest(
            week_key=args.week,
            output_path=Path(args.output) if args.output else None,
        )
        print(
            f"Digest build complete: week={result.week_key} candidates={result.candidate_count} "
            f"claude_used={result.claude_used} output={result.output_path}"
        )
        return 0

    if args.command == "send":
        print(f"Digest send skeleton for week={args.week}")
        return 0

    if args.command == "inspect":
        repo_root = Path(__file__).resolve().parents[3]
        service = DigestService(repo_root=repo_root)
        result = service.build_shortlist(args.week)
        print(f"Digest inspect: week={result.week_key} candidates={result.candidate_count}")
        for index, candidate in enumerate(result.candidates, start=1):
            published_ts = candidate.published_ts.isoformat() if candidate.published_ts else "unknown"
            print(f"{index}. {candidate.title}")
            print(f"   source={candidate.source_id} score={candidate.score} published_ts={published_ts}")
            print(f"   canonical_event_id={candidate.canonical_event_id}")
            print(f"   normalized_item_id={candidate.normalized_item_id}")
            print(f"   url={candidate.canonical_url}")
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
