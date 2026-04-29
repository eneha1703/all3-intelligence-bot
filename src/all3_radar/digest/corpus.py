"""Weekly digest corpus loading helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

WEEK_KEY_RE = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")


@dataclass(frozen=True)
class DigestCandidate:
    canonical_event_id: str
    normalized_item_id: str
    source_id: str
    title: str
    canonical_url: str
    published_ts: datetime | None
    score: int
    summary_text: str | None
    event_flags: dict[str, bool]


def parse_week_key(week_key: str) -> tuple[date, date]:
    normalized = week_key.strip()
    if normalized == "latest":
        today = datetime.now(timezone.utc).date()
        iso_year, iso_week, _ = today.isocalendar()
    else:
        match = WEEK_KEY_RE.match(normalized)
        if not match:
            raise ValueError(f"Invalid week key: {week_key!r}")
        iso_year = int(match.group("year"))
        iso_week = int(match.group("week"))
    week_start = date.fromisocalendar(iso_year, iso_week, 1)
    week_end = date.fromisocalendar(iso_year, iso_week, 7)
    return week_start, week_end


def build_default_output_path(repo_root: Path, week_key: str) -> Path:
    safe_week = week_key.replace("/", "_")
    return repo_root / "data" / f"weekly_digest_{safe_week}.md"


def hydrate_digest_candidates(rows: list[dict[str, Any]]) -> list[DigestCandidate]:
    candidates: list[DigestCandidate] = []
    for row in rows:
        signals = json.loads(row["signals_json"] or "{}")
        event_flags = signals.get("event_flags", {}) if isinstance(signals, dict) else {}
        candidates.append(
            DigestCandidate(
                canonical_event_id=str(row["canonical_event_id"]),
                normalized_item_id=str(row["normalized_item_id"]),
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                canonical_url=str(row["canonical_url"]),
                published_ts=datetime.fromisoformat(row["published_ts"]) if row.get("published_ts") else None,
                score=int(row["score"]),
                summary_text=row.get("summary_text"),
                event_flags={key: bool(value) for key, value in event_flags.items()},
            )
        )
    return candidates


def build_claude_corpus_prompt(week_key: str, candidates: list[DigestCandidate], max_items: int) -> str:
    selected = candidates[:max_items]
    lines = [
        f"You are drafting a weekly markdown synthesis for Bot 1 for week {week_key}.",
        "Use only the provided items.",
        "Return markdown that starts with '## Claude Synthesis'.",
        "Include 3 to 5 short bullets covering the most important cross-story themes.",
        "Then add one short paragraph explaining why the week's signals matter operationally.",
        "Do not invent facts, companies, funding amounts, or outcomes not present in the input.",
        "Do not repeat every headline one by one.",
        "",
        "Input items:",
    ]
    for index, candidate in enumerate(selected, start=1):
        published_label = candidate.published_ts.date().isoformat() if candidate.published_ts else "unknown-date"
        summary = candidate.summary_text or "(no summary stored)"
        lines.extend(
            [
                f"{index}. Title: {candidate.title}",
                f"   Source: {candidate.source_id}",
                f"   Published: {published_label}",
                f"   Score: {candidate.score}",
                f"   URL: {candidate.canonical_url}",
                f"   Summary: {summary}",
            ]
        )
    return "\n".join(lines)
