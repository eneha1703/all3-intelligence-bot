"""Weekly digest corpus loading helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WEEK_KEY_RE = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")
MODULE_DIR = Path(__file__).resolve().parent
WEEKLY_STYLE_GUIDE_PATH = MODULE_DIR / "weekly_style_guide.md"
WEEKLY_WRITER_EXAMPLES_PATH = MODULE_DIR / "weekly_writer_examples.json"


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


@dataclass(frozen=True)
class DigestWindow:
    week_key: str
    previous_thursday: date
    current_thursday: date
    iso_week_number: int
    title: str


def _normalize_current_thursday(week_key: str, today: date | None = None) -> date:
    normalized = week_key.strip()
    if normalized == "latest":
        resolved_today = today or datetime.now(timezone.utc).date()
        offset = (resolved_today.weekday() - 3) % 7
        return resolved_today - timedelta(days=offset)

    match = WEEK_KEY_RE.match(normalized)
    if not match:
        raise ValueError(f"Invalid week key: {week_key!r}")
    iso_year = int(match.group("year"))
    iso_week = int(match.group("week"))
    return date.fromisocalendar(iso_year, iso_week, 4)


def _format_digest_range(previous_thursday: date, current_thursday: date) -> str:
    if previous_thursday.year == current_thursday.year and previous_thursday.month == current_thursday.month:
        return f"{previous_thursday.day}-{current_thursday.day} {current_thursday.strftime('%B %Y')}"
    if previous_thursday.year == current_thursday.year:
        return (
            f"{previous_thursday.day} {previous_thursday.strftime('%B')}-"
            f"{current_thursday.day} {current_thursday.strftime('%B %Y')}"
        )
    return (
        f"{previous_thursday.day} {previous_thursday.strftime('%B %Y')}-"
        f"{current_thursday.day} {current_thursday.strftime('%B %Y')}"
    )


def resolve_digest_window(week_key: str, today: date | None = None) -> DigestWindow:
    current_thursday = _normalize_current_thursday(week_key, today=today)
    previous_thursday = current_thursday - timedelta(days=7)
    iso_year, iso_week, _ = current_thursday.isocalendar()
    normalized_week_key = f"{iso_year}-W{iso_week:02d}"
    title = (
        f"Top 5 News Highlights | "
        f"{_format_digest_range(previous_thursday, current_thursday)} | "
        f"Week {iso_week}"
    )
    return DigestWindow(
        week_key=normalized_week_key,
        previous_thursday=previous_thursday,
        current_thursday=current_thursday,
        iso_week_number=iso_week,
        title=title,
    )


def parse_week_key(week_key: str) -> tuple[date, date]:
    window = resolve_digest_window(week_key)
    return window.previous_thursday, window.current_thursday


def build_default_output_path(repo_root: Path, week_key: str) -> Path:
    safe_week = week_key.replace("/", "_")
    return repo_root / "data" / f"weekly_digest_{safe_week}.md"


def build_report_output_path(repo_root: Path, week_key: str) -> Path:
    safe_week = week_key.replace("/", "_")
    return repo_root / "data" / f"weekly_digest_{safe_week}.report.md"


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


@lru_cache(maxsize=1)
def _load_weekly_style_guide() -> str:
    return WEEKLY_STYLE_GUIDE_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _load_weekly_writer_examples() -> list[dict[str, Any]]:
    payload = json.loads(WEEKLY_WRITER_EXAMPLES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Weekly writer examples payload must be a list.")
    examples: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        examples.append(entry)
    return examples


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


def build_claude_selection_prompt(
    window: DigestWindow,
    candidates: list[DigestCandidate],
    max_items: int,
    mandatory_ids: tuple[str, ...] = (),
) -> str:
    selected = candidates[:max_items]
    payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "normalized_item_id": candidate.normalized_item_id,
            "source": candidate.source_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
            "score": candidate.score,
            "summary": candidate.summary_text,
            "signals": candidate.event_flags,
        }
        for candidate in selected
    ]
    lines = [
            "You are selecting the Top 5 weekly digest stories for Bot 2.",
            f"Digest title: {window.title}",
            f"Digest window: {window.previous_thursday.isoformat()} through {window.current_thursday.isoformat()}",
            "Select exactly 5 distinct stories from the provided candidates.",
            "Prioritize All3 relevance, physical AI, industrial robotics, construction automation, housing industrialization, timber adoption/scaling/economics/policy, infrastructure automation, strategic signal strength, novelty, and hard operational evidence.",
            "Prefer stories with a sharp operational takeaway, not just category relevance.",
            "Do not elevate timber logistics, marine terminal redevelopment, distribution hubs, or generic supply-chain positioning unless the story clearly changes adoption economics, building delivery, code acceptance, or project execution.",
            "Reject duplicate coverage of the same event and weak generic commentary.",
            "Consumer AI, restaurant/menu personalization AI, generic automotive capex, generic trade-policy stories, and generic executive/profile stories should not make the Top 5 unless robotics/automation is central.",
    ]
    if mandatory_ids:
        lines.extend(
            [
                "The following canonical_event_id values are mandatory and must be included in selected_ids:",
                json.dumps(list(mandatory_ids), ensure_ascii=False, sort_keys=True),
            ]
        )
    lines.extend(
        [
            "Return only compact JSON with this exact schema:",
            '{"selected_ids":["canonical_event_id_1","canonical_event_id_2","canonical_event_id_3","canonical_event_id_4","canonical_event_id_5"]}',
            "",
            "Candidates JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )
    return "\n".join(lines)


def build_claude_vote_selection_prompt(
    window: DigestWindow,
    *,
    shortlisted_candidates: list[DigestCandidate],
    vote_candidates: list[DigestCandidate],
    max_items: int,
    seats_to_fill: int,
) -> str:
    selected = vote_candidates[:max_items]
    payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "normalized_item_id": candidate.normalized_item_id,
            "source": candidate.source_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
            "score": candidate.score,
            "summary": candidate.summary_text,
            "signals": candidate.event_flags,
        }
        for candidate in selected
    ]
    fixed_payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "score": candidate.score,
        }
        for candidate in shortlisted_candidates
    ]
    lines = [
        "You are preparing a Telegram voting slate for the weekly digest.",
        f"Digest title: {window.title}",
        f"Already shortlisted count: {len(shortlisted_candidates)}",
        f"Seats still to fill: {seats_to_fill}",
        f"Select exactly {min(len(selected), max(3, seats_to_fill + 2))} distinct candidates for the vote slate.",
        "The vote slate should help the team choose the remaining digest stories.",
        "Prefer sharp, non-duplicative, high-signal stories with a good topic mix.",
        "Do not include candidates that are too close to each other or to the already shortlisted stories.",
        "Avoid generic funding, generic supply-chain, weak commentary, and duplicate event coverage.",
        "Return only compact JSON with this exact schema:",
        '{"selected_ids":["canonical_event_id_1","canonical_event_id_2","canonical_event_id_3"]}',
        "",
        "Already shortlisted JSON:",
        json.dumps(fixed_payload, ensure_ascii=False, sort_keys=True),
        "",
        "Vote candidates JSON:",
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    ]
    return "\n".join(lines)


def build_claude_writer_prompt(window: DigestWindow, candidates: list[DigestCandidate]) -> str:
    payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "source": candidate.source_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
            "score": candidate.score,
            "summary": candidate.summary_text,
            "signals": candidate.event_flags,
        }
        for candidate in candidates
    ]
    style_guide = _load_weekly_style_guide()
    examples = _load_weekly_writer_examples()
    return "\n".join(
        [
            "Write the final Weekly Digest Bot 2 message in Telegram HTML.",
            "English only, even when a source is non-English.",
            "Write like a smart human editor producing a short weekly strategic note.",
            "Be concise, analytical, natural, and non-hyped.",
            "Sound like a sharp human editor, not a consultant memo and not an AI summary engine.",
            "Do not sound like an AI assistant, a press release, or a database recap.",
            "Use exactly 5 items and keep each item to one compact paragraph.",
            "Aim for roughly 55 to 90 words per item.",
            "Prefer 2 to 4 sentences per item.",
            "The first line must be the digest title exactly as provided.",
            "For each item use this structure:",
            "1. <b>Headline</b>",
            'Paragraph ending with <a href="SOURCE_URL">Link</a>',
            "Do not show raw URLs in visible text.",
            "Do not invent facts beyond the provided input.",
            "Lead each paragraph with the strongest fact, then add one concise implication.",
            "Make the implication specific and observed from the facts, not broad and generic.",
            "Vary the framing across items instead of repeating the same conclusion formula.",
            "Use currency formatting like USD 120B, USD 25M, and EUR 100M.",
            "Do not use first-person company framing such as 'we', 'our', 'our need', 'our goals', or 'our strategy'.",
            "The implication can be about All3, the sector, physical AI, robotics, timber adoption, industrial systems, infrastructure, or construction more broadly.",
            "Do not force every item to explain why it matters specifically to All3.",
            "Do not simply restate the source headline in either the bold headline or the first sentence.",
            "Do not repeat the same core fact or idea in the headline and the first sentence with only minor wording changes.",
            "If the headline already carries the funding, deployment, or policy fact, the first sentence should add the most useful extra detail or move to a sharper angle.",
            "Do not default to starting every paragraph with the company name.",
            "Often it is better to start with the strongest fact, metric, market shift, deployment scale, or construction detail.",
            "Do not write bland summaries like 'Company X raised money for Y' unless the deeper point is made clear.",
            "Avoid vague abstractions such as 'recognition', 'direction', 'logic', 'meaningful bet', or 'important signal' unless you immediately tie them to a concrete mechanism.",
            "Do not use padded strategy-speak like 'this reflects broader recognition' when a sharper factual angle is available.",
            "Do not overstate with speculative lines like 'this could compress the gap' unless the provided facts directly support that claim.",
            "If a better sharp angle is not available, stay concrete and restrained rather than sounding clever.",
            "Do not end every item with generic phrases like 'the signal is', 'this highlights', or 'this underscores'.",
            "Mix the editorial voice across items so the digest reads like it was written by a person, not a template.",
            "If an item does not support a strong interpretive angle from the provided facts, stay concrete and restrained rather than inventing significance.",
            f"Title: {window.title}",
            "",
            "House style guide:",
            style_guide,
            "",
            "Reference examples:",
            json.dumps(examples, ensure_ascii=False, sort_keys=True),
            "",
            "Selected items JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )
