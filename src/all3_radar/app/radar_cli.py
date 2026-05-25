"""CLI entry points for the News Radar Bot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from all3_radar.config.loader import load_settings
from all3_radar.discovery.service import run_web_discovery
from all3_radar.pipeline.radar_service import run_radar
from all3_radar.pipeline.replay_service import replay_radar_window
from all3_radar.storage.repositories import RadarRepository
from all3_radar.telegram_interactions.callbacks import TelegramBotApiClient, handle_telegram_callback_update
from all3_radar.telegram_interactions.group_curation import TelegramGroupCurationService
from all3_radar.telegram_interactions.polling import poll_telegram_callback_updates, poll_telegram_interaction_updates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the All3 News Radar Bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the direct-source collection pipeline")
    run_parser.add_argument("--dry-run", action="store_true", help="Collect and persist without any downstream sending")
    run_parser.add_argument("--source", help="Run a single source id for debugging")

    discovery_parser = subparsers.add_parser(
        "discover-web",
        help="Run daily web discovery in report-only mode",
    )
    discovery_parser.add_argument(
        "--output-dir",
        help="Directory for markdown and JSON discovery reports. Defaults to data/web-discovery.",
    )

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

    telegram_update_parser = subparsers.add_parser(
        "telegram-handle-update",
        help="Handle one Telegram callback update from a JSON file",
    )
    telegram_update_parser.add_argument("update_json_file", help="Path to raw Telegram update JSON")

    telegram_poll_parser = subparsers.add_parser(
        "telegram-poll-updates",
        help="Poll Telegram for shortlist callbacks and optional group curation updates",
    )
    telegram_poll_parser.add_argument("--limit", type=int, default=50, help="Max updates to fetch in one polling call")
    telegram_poll_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Telegram long-poll timeout in seconds for this call",
    )
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

    if args.command == "discover-web":
        result = run_web_discovery(
            repo_root=repo_root,
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )
        print(
            f"Web discovery complete: candidates={len(result.evaluated_candidates)} "
            f"accepted_for_review={len(result.accepted_candidates)} "
            f"web_searches={result.web_search_requests}/{result.max_search_uses} "
            f"report={result.report_markdown_path}"
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

    if args.command == "telegram-handle-update":
        settings = load_settings(repo_root)
        repository = RadarRepository(settings.app.database_path)
        bot_api_client = TelegramBotApiClient(settings.integrations.telegram_alert_bot_token)
        update = json.loads(Path(args.update_json_file).read_text(encoding="utf-8"))
        callback_result = handle_telegram_callback_update(
            update,
            repository=repository,
            bot_api_client=bot_api_client,
        )
        curation_result = None
        if settings.telegram_group_curation.enabled:
            curation_result = TelegramGroupCurationService(
                repository,
                enabled=settings.telegram_group_curation.enabled,
                message_ingest_enabled=settings.telegram_group_curation.message_ingest_enabled,
                reaction_shortlist_enabled=settings.telegram_group_curation.reaction_shortlist_enabled,
                allowed_reaction_keys=settings.telegram_group_curation.shortlist_reaction_allowlist,
            ).ingest_update(update)
        print(
            f"Telegram update handled_callback={callback_result.handled} action={callback_result.action} "
            f"normalized_item_id={callback_result.normalized_item_id} active={callback_result.is_active} "
            f"stored_messages={curation_result.stored_messages if curation_result else 0} "
            f"stored_reaction_picks={curation_result.stored_reaction_picks if curation_result else 0} "
            f"message={callback_result.message}"
        )
        return 0

    if args.command == "telegram-poll-updates":
        settings = load_settings(repo_root)
        repository = RadarRepository(settings.app.database_path)
        bot_api_client = TelegramBotApiClient(settings.integrations.telegram_alert_bot_token)
        if settings.telegram_group_curation.enabled:
            curation_service = TelegramGroupCurationService(
                repository,
                enabled=settings.telegram_group_curation.enabled,
                message_ingest_enabled=settings.telegram_group_curation.message_ingest_enabled,
                reaction_shortlist_enabled=settings.telegram_group_curation.reaction_shortlist_enabled,
                allowed_reaction_keys=settings.telegram_group_curation.shortlist_reaction_allowlist,
            )
            result = poll_telegram_interaction_updates(
                repository=repository,
                bot_api_client=bot_api_client,
                curation_service=curation_service,
                limit=args.limit,
                timeout_seconds=args.timeout_seconds,
            )
            print(
                f"Telegram polling complete: fetched={result.fetched_updates} "
                f"handled_callbacks={result.handled_callbacks} stored_messages={result.stored_messages} "
                f"stored_reaction_picks={result.stored_reaction_picks} next_offset={result.next_offset}"
            )
            return 0
        result = poll_telegram_callback_updates(
            repository=repository,
            bot_api_client=bot_api_client,
            limit=args.limit,
            timeout_seconds=args.timeout_seconds,
        )
        print(
            f"Telegram polling complete: fetched={result.fetched_updates} "
            f"handled_callbacks={result.handled_callbacks} next_offset={result.next_offset}"
        )
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
