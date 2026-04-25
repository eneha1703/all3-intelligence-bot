"""CLI entry points for the Weekly Digest Bot."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the All3 Weekly Digest Bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    shortlist_parser = subparsers.add_parser("shortlist", help="Create a deterministic weekly shortlist")
    shortlist_parser.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")

    build_parser_cmd = subparsers.add_parser("build", help="Build the digest text with Claude")
    build_parser_cmd.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")

    send_parser = subparsers.add_parser("send", help="Send a previously built weekly digest")
    send_parser.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect digest candidates and output")
    inspect_parser.add_argument("--week", required=True, help="ISO week key, for example 2026-W17")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "shortlist":
        print(f"Digest shortlist skeleton for week={args.week}")
        return 0

    if args.command == "build":
        print(f"Digest build skeleton for week={args.week}")
        return 0

    if args.command == "send":
        print(f"Digest send skeleton for week={args.week}")
        return 0

    if args.command == "inspect":
        print(f"Digest inspect skeleton for week={args.week}")
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
