"""Human-readable audit report for ordinary News Radar runs."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from all3_radar.domain.models import RadarRunResult


_DUPLICATE_SKIP_REASONS = (
    "already_sent_same_funding_event",
    "already_sent_same_deployment_event",
    "duplicate_same_event_shortlist",
    "duplicate_same_partnership_event_shortlist",
    "duplicate_same_product_launch_event_shortlist",
)

_SEND_PROBLEM_SKIP_REASONS = (
    "weak_or_empty_telegram_card",
    "telegram_send_failed",
)

_KEY_SOURCE_IDS = (
    "destatis_press_listing",
    "haufe_immobilien_listing",
    "wood_central_api",
    "construction_news_intelligence_listing",
    "construction_briefing_rss",
    "humanoid_robotics_technology_listing",
)

_MAX_TOP_DECISION_ROWS = 40


def render_run_audit_markdown(
    result: RadarRunResult,
    decision_rows: list[dict[str, Any]],
    source_audit_rows: list[dict[str, Any]] | None = None,
    total_duration_seconds: float | None = None,
    stage_timings: dict[str, float] | None = None,
    stage_counters: dict[str, int] | None = None,
) -> str:
    skip_reason_counts = Counter(
        row["skip_reason"] for row in decision_rows if row.get("skip_reason")
    )
    sent_rows = [row for row in decision_rows if row.get("send_status") == "sent"]
    claude_editorial_rows = [
        row
        for row in decision_rows
        if _decode_signals(row.get("signals_json")).get("claude_editorial_reviewed") is True
    ]
    key_source_rows = [row for row in decision_rows if row.get("source_id") in _KEY_SOURCE_IDS]
    top_non_sent_rows = [
        row
        for row in decision_rows
        if row.get("send_status") != "sent"
        and (row.get("score") is not None and int(row.get("score") or 0) > 0)
    ][:_MAX_TOP_DECISION_ROWS]
    source_audit_rows = source_audit_rows or []
    failed_source_rows = [row for row in source_audit_rows if row.get("status") != "ok"]
    stage_timings = stage_timings or {}
    stage_counters = stage_counters or {}
    commit_sha = os.getenv("GITHUB_SHA") or "not available"
    github_run_id = os.getenv("GITHUB_RUN_ID")
    artifact_reference = f"radar-db-{github_run_id}" if github_run_id else "not available"

    lines = [
        "# News Radar Run Audit",
        "",
        f"- pipeline_run_id: `{result.run_id}`",
        f"- commit_sha: `{commit_sha}`",
        f"- db_artifact_reference: `{artifact_reference}`",
        "",
        "## Summary Counters",
        "",
        f"- collected: `{result.collected_items}`",
        f"- normalized: `{result.normalized_items}`",
        f"- fresh: `{result.fresh_items}`",
        f"- canonical_events: `{result.canonical_events}`",
        f"- shortlisted: `{result.shortlisted_items}`",
        f"- sent: `{result.sent_items}`",
        f"- send_skips: `{result.skipped_send_items}`",
        f"- failed_sources: `{result.failed_sources}`",
        f"- duration_seconds: `{_sanitize_cell(total_duration_seconds) or 'not available'}`",
    ]

    if stage_counters:
        lines.extend(
            [
                "",
                "## Stage Counters",
                "",
                "| Counter | Value |",
                "| --- | --- |",
            ]
        )
        for counter_name, value in stage_counters.items():
            lines.append(f"| {_sanitize_cell(counter_name)} | {_sanitize_cell(value)} |")

    if stage_timings:
        lines.extend(
            [
                "",
                "## Stage Timings",
                "",
                "| Stage | Duration Seconds |",
                "| --- | --- |",
            ]
        )
        for stage_name, duration_seconds in stage_timings.items():
            lines.append(f"| {_sanitize_cell(stage_name)} | {_sanitize_cell(duration_seconds)} |")

    lines.extend(
        [
            "",
            "## Skip Reason Counts",
            "",
        ]
    )

    if skip_reason_counts:
        for reason, count in sorted(skip_reason_counts.items()):
            lines.append(f"- `{reason}`: `{count}`")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Duplicate Suppression Counts",
            "",
        ]
    )
    for reason in _DUPLICATE_SKIP_REASONS:
        lines.append(f"- `{reason}`: `{skip_reason_counts.get(reason, 0)}`")

    lines.extend(
        [
            "",
            "## Send-Stage Problem Counts",
            "",
        ]
    )
    for reason in _SEND_PROBLEM_SKIP_REASONS:
        lines.append(f"- `{reason}`: `{skip_reason_counts.get(reason, 0)}`")

    lines.extend(
        [
            "",
            "## Sent Items",
            "",
            "| Title | Source | Card Writer | Summary Source | Claude Outcome | Claude Reason | Canonical URL |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if sent_rows:
        for row in sent_rows:
            title = _sanitize_cell(row.get("title"))
            source_id = _sanitize_cell(row.get("source_id"))
            canonical_url = _sanitize_cell(row.get("canonical_url"))
            signals = _decode_signals(row.get("signals_json"))
            card_writer = _sanitize_cell(signals.get("card_writer"))
            summary_source = _sanitize_cell(signals.get("final_card_summary_source"))
            claude_outcome = _sanitize_cell(signals.get("claude_final_card_outcome"))
            claude_reason = _sanitize_cell(signals.get("claude_final_card_reason"))
            lines.append(
                f"| {title} | {source_id} | {card_writer} | {summary_source} | "
                f"{claude_outcome} | {claude_reason} | {canonical_url} |"
            )
    else:
        lines.append("| none | none | none | none | none | none | none |")

    lines.extend(
        [
            "",
            "## Sent Item Summaries",
            "",
            "| Title | Summary Text |",
            "| --- | --- |",
        ]
    )
    if sent_rows:
        for row in sent_rows:
            title = _sanitize_cell(row.get("title"))
            summary_text = _sanitize_cell(row.get("summary_text"))
            lines.append(f"| {title} | {summary_text} |")
    else:
        lines.append("| none | none |")

    lines.extend(
        [
            "",
            "## Claude Editorial Reviewed Items",
            "",
            "| Title | Source | Score | Status | Skip Reason | Claude Outcome | Confidence | Claude Reason | Event Flags | Canonical URL |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if claude_editorial_rows:
        for row in claude_editorial_rows:
            lines.append(_render_decision_row(row))
    else:
        lines.append("| none | none | none | none | none | none | none | none | none | none |")

    lines.extend(
        [
            "",
            "## Top Non-Sent Decisions",
            "",
            "| Title | Source | Score | Status | Skip Reason | Claude Outcome | Confidence | Claude Reason | Event Flags | Canonical URL |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if top_non_sent_rows:
        for row in top_non_sent_rows:
            lines.append(_render_decision_row(row))
    else:
        lines.append("| none | none | none | none | none | none | none | none | none | none |")

    lines.extend(
        [
            "",
            "## Key Source Decisions",
            "",
            "| Title | Source | Score | Status | Skip Reason | Claude Outcome | Confidence | Claude Reason | Event Flags | Canonical URL |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if key_source_rows:
        for row in key_source_rows:
            lines.append(_render_decision_row(row))
    else:
        lines.append("| none | none | none | none | none | none | none | none | none | none |")

    lines.extend(
        [
            "",
            "## Source Failures",
            "",
            "| Source ID | Source Name | Status/Error | Items Collected | Duration Seconds |",
            "| --- | --- | --- | --- | --- |",
            "",
        ]
    )
    if failed_source_rows:
        for row in failed_source_rows:
            source_id = _sanitize_cell(row.get("source_id"))
            source_name = _sanitize_cell(row.get("source_name"))
            status = _sanitize_cell(row.get("status"))
            items_collected = _sanitize_cell(row.get("items_collected"))
            duration_seconds = _sanitize_cell(row.get("duration_seconds"))
            lines.append(f"| {source_id} | {source_name} | {status} | {items_collected} | {duration_seconds} |")
    else:
        lines.append("| none | none | none | none | none |")

    lines.extend(
        [
            "",
            "## Source Collection Counts",
            "",
            "| Source ID | Collected Items | Duration Seconds |",
            "| --- | --- | --- |",
        ]
    )
    if source_audit_rows:
        for row in source_audit_rows:
            source_id = _sanitize_cell(row.get("source_id"))
            items_collected = _sanitize_cell(row.get("items_collected"))
            duration_seconds = _sanitize_cell(row.get("duration_seconds"))
            lines.append(f"| {source_id} | {items_collected} | {duration_seconds} |")
    else:
        lines.append("| none | none | none |")

    return "\n".join(lines)


def write_run_audit_report(
    repo_root: Path,
    result: RadarRunResult,
    decision_rows: list[dict[str, Any]],
    source_audit_rows: list[dict[str, Any]] | None = None,
    total_duration_seconds: float | None = None,
    stage_timings: dict[str, float] | None = None,
    stage_counters: dict[str, int] | None = None,
) -> Path:
    report_path = repo_root / "data" / f"radar-run-audit-{result.run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_run_audit_markdown(
            result,
            decision_rows,
            source_audit_rows,
            total_duration_seconds,
            stage_timings,
            stage_counters,
        ),
        encoding="utf-8",
    )
    return report_path


def _sanitize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def _decode_signals(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _render_decision_row(row: dict[str, Any]) -> str:
    signals = _decode_signals(row.get("signals_json"))
    return (
        f"| {_sanitize_cell(row.get('title'))} "
        f"| {_sanitize_cell(row.get('source_id'))} "
        f"| {_sanitize_cell(row.get('score'))} "
        f"| {_sanitize_cell(row.get('send_status'))} "
        f"| {_sanitize_cell(row.get('skip_reason'))} "
        f"| {_sanitize_cell(signals.get('claude_editorial_outcome'))} "
        f"| {_sanitize_cell(signals.get('claude_editorial_confidence'))} "
        f"| {_sanitize_cell(_decision_reason(signals))} "
        f"| {_sanitize_cell(_event_flags_summary(signals))} "
        f"| {_sanitize_cell(row.get('canonical_url'))} |"
    )


def _decision_reason(signals: dict[str, Any]) -> str:
    return str(
        signals.get("claude_editorial_reason")
        or signals.get("claude_editorial_reject_reason")
        or signals.get("claude_editorial_not_reviewed_reason")
        or signals.get("claude_final_card_reason")
        or ""
    )


def _event_flags_summary(signals: dict[str, Any]) -> str:
    event_flags = signals.get("event_flags", {})
    if not isinstance(event_flags, dict):
        return ""
    enabled_flags = sorted(str(key) for key, value in event_flags.items() if value is True)
    return ", ".join(enabled_flags)
