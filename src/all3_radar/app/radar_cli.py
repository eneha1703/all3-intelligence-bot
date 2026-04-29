"""CLI entry points for the News Radar Bot."""

from __future__ import annotations

import argparse
from pathlib import Path

from all3_radar.pipeline.radar_service import run_radar
from all3_radar.pipeline.replay_service import replay_radar_window


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the All3 News Radar Bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the direct-source collection pipeline")
    run_parser.add_argument("--dry-run", action="store_true", help="Collect and persist without any downstream sending")
    run_parser.add_argument("--source", help="Run a single source id for debugging")

    replay_parser = subparsers.add_parser("replay-window", help="Replay a historical published-date window")
    replay_parser.add_argument("--start-date", required=True, help="Replay window start date in YYYY-MM-DD")
    replay_parser.add_argument("--end-date", required=True, help="Replay window end date in YYYY-MM-DD")
    replay_parser.add_argument("--label", required=True, help="Replay label to prepend to Telegram messages")
    replay_parser.add_argument(
        "--allowlist-urls-file",
        help="Optional text file with one allowlisted URL per line. When set, replay only sends matched URLs.",
    )
    replay_parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send replay cards to Telegram instead of only logging candidates",
    )

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
    repo_root = Path(__file__).resolve().parents[3]

    if args.command == "run":
        result = run_radar(repo_root=repo_root, source_id=args.source, dry_run=args.dry_run)
        print(
            f"Radar run complete: run_id={result.run_id} collected={result.collected_items} "
            f"normalized={result.normalized_items} fresh={result.fresh_items} "
            f"stale={result.stale_items} missing_published_ts={result.missing_published_ts} "
            f"canonical_events={result.canonical_events} shortlisted={result.shortlisted_items} "
            f"sent={result.sent_items} failed_sources={result.failed_sources}"
        )
        return 0

    if args.command == "replay-window":
        result = replay_radar_window(
            repo_root=repo_root,
            start_date=args.start_date,
            end_date=args.end_date,
            replay_label=args.label,
            send=args.send,
            allowlist_urls_file=Path(args.allowlist_urls_file) if args.allowlist_urls_file else None,
        )
        print(
            f"Replay run complete: run_id={result.run_id} window={args.start_date}..{args.end_date} "
            f"loaded={result.normalized_items} unique_events={result.canonical_events} "
            f"shortlisted={result.shortlisted_items} sent={result.sent_items} "
            f"skipped={result.skipped_send_items}"
        )
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
