"""Deterministic markdown writer for weekly digests."""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime, timezone

from all3_radar.digest.corpus import DigestCandidate
from all3_radar.summarization.fallback_summary import generate_fallback_summary

URL_RE = re.compile(r"https?://\S+")


def _default_candidate_paragraph(candidate: DigestCandidate) -> str:
    flags = candidate.event_flags
    if flags.get("construction_statistics_signal"):
        return (
            "Official housing and construction data added another hard market-pressure signal this week. "
            "Even without a company angle, the figures matter because they show where delivery strain remains visible."
        )
    if flags.get("timber_strategic_signal"):
        return (
            "The stronger angle here is not a single showcase asset but where timber is finding a practical route "
            "into real standards, assets, or delivery models."
        )
    if flags.get("industrial_robotics_signal") or flags.get("construction_innovation_signal"):
        return (
            "The more useful angle here is operational: it shows where robotics is moving from concept into a more "
            "concrete deployment or commercial path."
        )
    if flags.get("funding_event"):
        return (
            "The funding matters only if it supports a real operating wedge, and this story suggests investors still "
            "see one in the category."
        )
    return "This story remained one of the week's stronger operating signals across the All3 scope."


def _sanitize_summary_text(candidate: DigestCandidate) -> str:
    generated = generate_fallback_summary(candidate.title, candidate.summary_text)
    if generated:
        normalized = URL_RE.sub("", generated).strip()
    elif candidate.summary_text:
        normalized = URL_RE.sub("", candidate.summary_text).strip()
    else:
        normalized = _default_candidate_paragraph(candidate)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    if not normalized:
        return _default_candidate_paragraph(candidate)
    if normalized[-1] not in ".!?":
        normalized = f"{normalized}."
    return normalized


def _format_story_block(index: int, candidate: DigestCandidate) -> list[str]:
    published_label = candidate.published_ts.date().isoformat() if candidate.published_ts else "unknown-date"
    lines = [
        f"{index}. [{candidate.title}]({candidate.canonical_url})",
        f"   Source: `{candidate.source_id}` | Published: `{published_label}` | Score: `{candidate.score}`",
        f"   Story type: `{candidate.story_type}`",
    ]
    if candidate.angle_guard:
        lines.append(f"   Angle guard: {'; '.join(candidate.angle_guard)}")
    if candidate.summary_text:
        lines.append(f"   Summary: {candidate.summary_text}")
    return lines


def build_digest_html(title: str, candidates: list[DigestCandidate]) -> str:
    lines = [title]
    if not candidates:
        lines.extend(["", "No eligible stories were found for this digest window."])
        return "\n".join(lines)

    for index, candidate in enumerate(candidates, start=1):
        paragraph = _sanitize_summary_text(candidate)
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
    shortlist_candidates: list[DigestCandidate] | None = None,
    claude_used: bool = False,
    fallback_reason: str | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    shortlist_candidates = shortlist_candidates or candidates
    lines = [
        f"# Bot 1 Weekly Digest — {week_key}",
        "",
        f"Generated at: `{generated_at}`",
        f"Shortlist considered: `{len(shortlist_candidates)}`",
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
    lines.extend(["", "## Candidate Shortlist", ""])

    if not shortlist_candidates:
        lines.append("No eligible shortlist candidates were available for this week.")
    else:
        for index, candidate in enumerate(shortlist_candidates, start=1):
            lines.extend(_format_story_block(index, candidate))
            lines.append("")

    lines.extend(["## Top Stories", ""])

    if not candidates:
        lines.append("No eligible Bot 1 stories were found for this week.")
    else:
        for index, candidate in enumerate(candidates, start=1):
            lines.extend(_format_story_block(index, candidate))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
