"""CLI entry points for the News Radar Bot."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the All3 News Radar Bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full radar pipeline")
    run_parser.add_argument("--dry-run", action="store_true", help="Collect and score without sending Telegram messages")
    run_parser.add_argument("--source", help="Run a single source id for debugging")

    inspect_parser = subparsers.add_parser("inspect-run", help="Inspect a previous radar run")
    inspect_parser.add_argument("run_id", help="Pipeline run id")

    explain_parser = subparsers.add_parser("explain-item", help="Explain a stored item decision")
    explain_parser.add_argument("item_id", help="Normalized item id")

    resend_parser = subparsers.add_parser("resend", help="Resend a previously approved radar item")
    resend_parser.add_argument("item_id", help="Normalized item id")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        print("Radar pipeline skeleton: collection, filtering, ranking, summaries, and Telegram delivery.")
        if args.dry_run:
            print("Dry run enabled: Telegram sending is disabled.")
        if args.source:
            print(f"Source override: {args.source}")
        return 0

    if args.command == "inspect-run":
        print(f"Inspect run skeleton for run_id={args.run_id}")
        return 0

    if args.command == "explain-item":
        print(f"Explain item skeleton for item_id={args.item_id}")
        return 0

    if args.command == "resend":
        print(f"Resend skeleton for item_id={args.item_id}")
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
