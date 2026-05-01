"""Deterministic markdown writer for weekly digests."""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime, timezone

from all3_radar.digest.corpus import DigestCandidate

URL_RE = re.compile(r"https?://\S+")


def _sanitize_summary_text(summary_text: str | None) -> str:
    if not summary_text:
        return "This story remained one of the week's strongest operational signals across the All3 scope."
    normalized = URL_RE.sub("", summary_text).strip()
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    if not normalized:
        return "This story remained one of the week's strongest operational signals across the All3 scope."
    if normalized[-1] not in ".!?":
        normalized = f"{normalized}."
    return normalized


def _format_story_block(index: int, candidate: DigestCandidate) -> list[str]:
    published_label = candidate.published_ts.date().isoformat() if candidate.published_ts else "unknown-date"
    lines = [
        f"{index}. [{candidate.title}]({candidate.canonical_url})",
        f"   Source: `{candidate.source_id}` | Published: `{published_label}` | Score: `{candidate.score}`",
    ]
    if candidate.summary_text:
        lines.append(f"   Summary: {candidate.summary_text}")
    return lines


def build_digest_html(title: str, candidates: list[DigestCandidate]) -> str:
    lines = [title]
    if not candidates:
        lines.extend(["", "No eligible stories were found for this digest window."])
        return "\n".join(lines)

    for index, candidate in enumerate(candidates, start=1):
        paragraph = _sanitize_summary_text(candidate.summary_text)
        lines.extend(
            [
                "",
                f"{index}. <b>{html.escape(candidate.title)}</b>",
                f'{html.escape(paragraph)} <a href="{html.escape(candidate.canonical_url, quote=True)}">Link</a>',
            ]
        )
    return "\n".join(lines)


def _build_signal_snapshot(candidates: list[DigestCandidate]) -> list[str]:
    counts = Counter()
    for candidate in candidates:
        for flag_name, flag_value in candidate.event_flags.items():
            if flag_value:
                counts[flag_name] += 1

    snapshot_order = [
        ("funding_event", "Funding signals"),
        ("partnership_event", "Partnership signals"),
        ("deployment_event", "Deployment signals"),
        ("industrial_robotics_signal", "Industrial robotics signals"),
        ("construction_innovation_signal", "Construction innovation signals"),
        ("timber_strategic_signal", "Timber strategy signals"),
        ("construction_statistics_signal", "Official construction statistics"),
    ]
    lines: list[str] = []
    for key, label in snapshot_order:
        if counts[key]:
            lines.append(f"- {label}: {counts[key]}")
    if not lines:
        lines.append("- No high-level event flag counts were available in the stored decisions.")
    return lines


def build_digest_markdown(
    week_key: str,
    candidates: list[DigestCandidate],
    claude_section: str | None = None,
    *,
    claude_used: bool = False,
    fallback_reason: str | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# Bot 1 Weekly Digest — {week_key}",
        "",
        f"Generated at: `{generated_at}`",
        f"Stories included: `{len(candidates)}`",
        "",
    ]

    if claude_section:
        lines.extend([claude_section.strip(), ""])

    lines.extend(["## Claude Digest Status", ""])
    lines.append(f"- Claude used: {'yes' if claude_used else 'no'}")
    lines.append(f"- Fallback reason: {fallback_reason or 'none'}")
    if candidates:
        lines.append("- Final selected titles:")
        for candidate in candidates:
            lines.append(f"  - {candidate.title}")
    lines.append("")

    lines.extend(["## Signals Snapshot", ""])
    lines.extend(_build_signal_snapshot(candidates))
    lines.extend(["", "## Top Stories", ""])

    if not candidates:
        lines.append("No eligible Bot 1 stories were found for this week.")
    else:
        for index, candidate in enumerate(candidates, start=1):
            lines.extend(_format_story_block(index, candidate))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
