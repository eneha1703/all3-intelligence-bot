from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from all3_radar.delivery.telegram import TelegramSender
from all3_radar.domain.models import ClaudeFinalCardResult, TelegramCard
from all3_radar.summarization.claude_final_card_client import (
    ClaudeFinalCardClient,
    ClaudeFinalCardUnavailableError,
)

PREVIEW_BOT_TOKEN_ENV = "TELEGRAM_CLAUDE_PREVIEW_BOT_TOKEN"
PREVIEW_CHAT_IDS_ENV = "TELEGRAM_CLAUDE_PREVIEW_CHAT_IDS"


@dataclass(frozen=True)
class PreviewStory:
    title: str
    canonical_url: str
    source_name: str
    text_preview: str | None
    existing_summary: str | None
    score: int
    event_flags: dict[str, object]
    signals: dict[str, object]


@dataclass(frozen=True)
class PreviewOutcome:
    story: PreviewStory
    status: str
    card: TelegramCard | None
    error_text: str | None
    telegram_statuses: tuple[str, ...] = ()


def _parse_chat_ids(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _sentence_split(text: str) -> list[str]:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []
    parts: list[str] = []
    start = 0
    for index, char in enumerate(normalized):
        if char in ".!?":
            segment = normalized[start : index + 1].strip()
            if segment:
                parts.append(segment)
            start = index + 1
    tail = normalized[start:].strip()
    if tail:
        if tail[-1] not in ".!?":
            tail = f"{tail}."
        parts.append(tail)
    return parts


def _build_preview_body(summary: str, why_it_matters: str | None) -> str:
    sentences = _sentence_split(summary)
    if len(sentences) < 2 and why_it_matters:
        extra = _sentence_split(why_it_matters)
        for sentence in extra:
            if sentence not in sentences:
                sentences.append(sentence)
            if len(sentences) >= 2:
                break
    if not sentences:
        raise ValueError("Preview card summary was empty.")
    return " ".join(sentences[:3])


def _build_preview_card(story: PreviewStory, result: ClaudeFinalCardResult) -> TelegramCard:
    if not result.send_ok or not result.title or not result.summary:
        raise ValueError("Preview card requires send_ok title and summary.")
    body = _build_preview_body(result.summary, result.why_it_matters)
    text = "\n\n".join(
        [
            f"<b>{html.escape(result.title)}</b>",
            html.escape(body),
            f'<a href="{html.escape(story.canonical_url, quote=True)}">Link</a>',
            html.escape(story.source_name),
        ]
    )
    return TelegramCard(text=text, headline=result.title, summary_text=body, url=story.canonical_url)


@contextmanager
def _resolve_artifact_db(artifact_path: Path) -> Iterator[Path]:
    if artifact_path.suffix.lower() == ".db":
        yield artifact_path
        return
    if artifact_path.suffix.lower() != ".zip":
        raise ValueError(f"Unsupported artifact path: {artifact_path}")
    with tempfile.TemporaryDirectory(prefix="claude-final-card-preview-") as temp_dir:
        extract_root = Path(temp_dir)
        with zipfile.ZipFile(artifact_path) as archive:
            archive.extractall(extract_root)
        matches = list(extract_root.rglob("all3_radar.db"))
        if not matches:
            raise ValueError(f"No all3_radar.db found in artifact zip: {artifact_path}")
        yield matches[0]


def open_readonly_connection(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _load_stories(connection: sqlite3.Connection, run_id: str | None, title_filters: Sequence[str]) -> list[PreviewStory]:
    where_clauses = []
    params: list[object] = []
    if run_id:
        where_clauses.append("ri.run_id = ?")
        params.append(run_id)
    if title_filters:
        filter_clauses = []
        for value in title_filters:
            filter_clauses.append("LOWER(ni.title) LIKE ?")
            params.append(f"%{value.lower()}%")
        where_clauses.append("(" + " OR ".join(filter_clauses) + ")")
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    rows = connection.execute(
        f"""
        SELECT
            ni.title,
            ni.canonical_url,
            COALESCE(src.name, ni.source_id) AS source_name,
            ni.text_preview,
            rd.summary_text,
            COALESCE(rd.score, 0) AS score,
            rd.signals_json
        FROM normalized_items ni
        JOIN raw_items ri ON ri.id = ni.raw_item_id
        LEFT JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
        LEFT JOIN sources src ON src.id = ni.source_id
        WHERE {where_sql}
        ORDER BY ri.collected_ts DESC, ni.title ASC
        """
    , params).fetchall()

    stories: list[PreviewStory] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["title"], row["canonical_url"])
        if key in seen:
            continue
        seen.add(key)
        signals = json.loads(row["signals_json"]) if row["signals_json"] else {}
        stories.append(
            PreviewStory(
                title=row["title"],
                canonical_url=row["canonical_url"],
                source_name=row["source_name"],
                text_preview=row["text_preview"],
                existing_summary=row["summary_text"],
                score=int(row["score"] or 0),
                event_flags=dict(signals.get("event_flags") or {}),
                signals=signals,
            )
        )
    return stories


def _build_client(environ: dict[str, str] | None = None) -> ClaudeFinalCardClient:
    environ = environ or dict(os.environ)
    return ClaudeFinalCardClient(
        enabled=True,
        api_key=(environ.get("ANTHROPIC_API_KEY") or "").strip() or None,
        model=(environ.get("CLAUDE_FINAL_CARD_MODEL") or "claude-3-5-sonnet-latest").strip() or None,
        timeout_seconds=int((environ.get("CLAUDE_FINAL_CARD_TIMEOUT_SECONDS") or "12").strip() or "12"),
        max_tokens=int((environ.get("CLAUDE_FINAL_CARD_MAX_TOKENS") or "300").strip() or "300"),
    )


def _build_preview_sender(environ: dict[str, str] | None = None) -> TelegramSender:
    environ = environ or dict(os.environ)
    bot_token = (environ.get(PREVIEW_BOT_TOKEN_ENV) or "").strip() or None
    chat_ids = _parse_chat_ids(environ.get(PREVIEW_CHAT_IDS_ENV))
    return TelegramSender(bot_token=bot_token, chat_ids=chat_ids)


def _render_preview_markdown(
    artifact_path: Path,
    run_id: str | None,
    outcomes: Sequence[PreviewOutcome],
) -> str:
    lines = [
        "# Claude Final Card Preview",
        "",
        f"Artifact: {artifact_path}",
        f"Run ID: {run_id or 'latest available in artifact query'}",
        "",
    ]
    for outcome in outcomes:
        lines.append(f"## {outcome.story.title}")
        lines.append("")
        lines.append(f"Status: {outcome.status}")
        if outcome.error_text:
            lines.append(f"Reason: {outcome.error_text}")
        if outcome.telegram_statuses:
            lines.append(f"Telegram deliveries: {', '.join(outcome.telegram_statuses)}")
        lines.append("")
        if outcome.card:
            lines.append(outcome.card.text)
            lines.append("")
        else:
            lines.append(f"Link: {outcome.story.canonical_url}")
            lines.append(outcome.story.source_name)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def run_preview(
    *,
    artifact_path: Path,
    run_id: str | None,
    title_filters: Sequence[str],
    output_path: Path,
    send_telegram: bool,
    environ: dict[str, str] | None = None,
    client: ClaudeFinalCardClient | None = None,
    sender: TelegramSender | None = None,
) -> list[PreviewOutcome]:
    environ = environ or dict(os.environ)
    client = client or _build_client(environ)
    sender = sender or _build_preview_sender(environ)

    with _resolve_artifact_db(artifact_path) as db_path:
        with open_readonly_connection(db_path) as connection:
            stories = _load_stories(connection, run_id, title_filters)

    if not stories:
        raise SystemExit("No matching stories found in artifact.")

    if send_telegram and not sender.is_configured:
        raise SystemExit(
            f"{PREVIEW_BOT_TOKEN_ENV} and {PREVIEW_CHAT_IDS_ENV} must be configured for --send-telegram."
        )

    outcomes: list[PreviewOutcome] = []
    for story in stories:
        try:
            result = client.generate_final_card(
                title=story.title,
                source=story.source_name,
                url=story.canonical_url,
                text_preview=story.text_preview,
                score=story.score,
                event_flags=story.event_flags,
                signals=story.signals,
                existing_summary=story.existing_summary,
            )
            if not result.send_ok:
                outcomes.append(
                    PreviewOutcome(
                        story=story,
                        status="rejected",
                        card=None,
                        error_text=result.reject_reason or "Claude rejected the story.",
                    )
                )
                continue
            card = _build_preview_card(story, result)
            telegram_statuses: tuple[str, ...] = ()
            if send_telegram:
                deliveries = sender.send_card(card)
                telegram_statuses = tuple(f"{delivery.chat_id}:{delivery.status}" for delivery in deliveries)
            outcomes.append(
                PreviewOutcome(
                    story=story,
                    status="success",
                    card=card,
                    error_text=None,
                    telegram_statuses=telegram_statuses,
                )
            )
        except (ClaudeFinalCardUnavailableError, ValueError) as exc:
            outcomes.append(
                PreviewOutcome(
                    story=story,
                    status="failed",
                    card=None,
                    error_text=str(exc),
                )
            )

    output_path.write_text(_render_preview_markdown(artifact_path, run_id, outcomes), encoding="utf-8")
    return outcomes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview Claude-written Telegram cards from an artifact DB.")
    parser.add_argument("--artifact", required=True, help="Path to artifact .db or .zip")
    parser.add_argument("--run-id", default=None, help="Optional radar run id filter")
    parser.add_argument("--title", action="append", default=[], help="Case-insensitive title substring filter")
    parser.add_argument(
        "--output",
        default="tmp_claude_final_card_preview.md",
        help="Path for local preview markdown output",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send preview cards to preview Telegram bot/chat ids using preview-only env vars",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    run_preview(
        artifact_path=Path(args.artifact),
        run_id=args.run_id,
        title_filters=args.title,
        output_path=Path(args.output),
        send_telegram=bool(args.send_telegram),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
