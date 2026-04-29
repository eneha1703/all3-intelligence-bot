"""Human-readable audit report for ordinary News Radar runs."""

from __future__ import annotations

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
            "| Title | Source | Canonical URL |",
            "| --- | --- | --- |",
        ]
    )
    if sent_rows:
        for row in sent_rows:
            title = _sanitize_cell(row.get("title"))
            source_id = _sanitize_cell(row.get("source_id"))
            canonical_url = _sanitize_cell(row.get("canonical_url"))
            lines.append(f"| {title} | {source_id} | {canonical_url} |")
    else:
        lines.append("| none | none | none |")

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
