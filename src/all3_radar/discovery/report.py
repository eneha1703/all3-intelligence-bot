"""Report writing for web discovery runs."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from all3_radar.discovery.models import DiscoveryRunResult, EvaluatedDiscoveryCandidate

SEARCH_COST_USD = 0.01
PRESS_RELEASE_SOURCE_MARKERS = (
    "pr newswire",
    "business wire",
    "globe newswire",
    "globenewswire",
    "stock titan",
    "ein presswire",
)
TABLOID_SOURCE_MARKERS = (
    "new york post",
    "the sun",
    "daily mail",
    "mirror",
)


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _safe(value: str | None) -> str:
    return (value or "").replace("\n", " ").strip()


def _looks_like_press_release_rehost(evaluated: EvaluatedDiscoveryCandidate) -> bool:
    candidate = evaluated.candidate
    haystacks = (
        candidate.url.lower(),
        (candidate.source_name or "").lower(),
        candidate.title.lower(),
    )
    return any(marker in haystack for haystack in haystacks for marker in PRESS_RELEASE_SOURCE_MARKERS)


def _looks_like_tabloid_source(evaluated: EvaluatedDiscoveryCandidate) -> bool:
    candidate = evaluated.candidate
    haystacks = (
        candidate.url.lower(),
        (candidate.source_name or "").lower(),
        candidate.title.lower(),
    )
    return any(marker in haystack for haystack in haystacks for marker in TABLOID_SOURCE_MARKERS)


def _candidate_line(index: int, evaluated: EvaluatedDiscoveryCandidate) -> str:
    candidate = evaluated.candidate
    line = f"{index}. [{candidate.title}]({candidate.url})"
    details = [
        f"pack=`{candidate.query_pack_id}`",
        f"confidence=`{candidate.confidence}`",
    ]
    if candidate.source_name:
        details.append(f"source={candidate.source_name}")
    if candidate.published_date:
        details.append(f"published={candidate.published_date}")
    if _looks_like_press_release_rehost(evaluated):
        details.append("source_quality=`press_release_rehost`")
    elif _looks_like_tabloid_source(evaluated):
        details.append("source_quality=`tabloid_verify_better_source`")
    return f"{line}\n   " + " | ".join(details)


def _candidate_priority(evaluated: EvaluatedDiscoveryCandidate) -> str:
    candidate = evaluated.candidate
    if _looks_like_press_release_rehost(evaluated):
        return "verify_primary_source"
    if _looks_like_tabloid_source(evaluated):
        return "watch_only"
    if candidate.confidence == "high":
        return "likely_post"
    return "watch_only"


def _rejection_counts(result: DiscoveryRunResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in result.evaluated_candidates:
        if item.accepted_for_review:
            continue
        reason = item.rejection_reason or item.dedupe.reason or "not_accepted"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def build_discovery_report(result: DiscoveryRunResult) -> str:
    estimated_search_cost = result.web_search_requests * SEARCH_COST_USD
    lines = [
        "# Daily Web Discovery Report",
        "",
        f"Generated at: `{result.generated_at.isoformat()}`",
        f"Provider: `{result.provider}`",
        f"Model: `{result.model}`",
        f"Web searches used: `{result.web_search_requests}` / `{result.max_search_uses}`",
        f"Estimated search-tool cost: `${estimated_search_cost:.2f}` before token costs",
        f"Candidates returned: `{len(result.evaluated_candidates)}`",
        f"New candidates accepted for review: `{len(result.accepted_candidates)}`",
        "",
        "## Executive Summary",
        "",
    ]
    if result.accepted_candidates:
        for index, evaluated in enumerate(result.accepted_candidates, start=1):
            candidate = evaluated.candidate
            lines.append(
                f"- `{_candidate_priority(evaluated)}` [{candidate.title}]({candidate.url}) "
                f"({candidate.source_name or 'unknown source'}, confidence=`{candidate.confidence}`)"
            )
    else:
        lines.append("- No candidates passed freshness, dedupe, source-quality, and scope gates.")
    rejection_counts = _rejection_counts(result)
    if rejection_counts:
        lines.extend(
            [
                "",
                "Skipped/rejected counts:",
                "",
            ]
        )
        for reason, count in rejection_counts.items():
            lines.append(f"- `{reason}`: `{count}`")
    lines.extend(
        [
            "",
            "Review guidance:",
            "",
            "- `likely_post`: strongest manual-review candidate.",
            "- `verify_primary_source`: potentially useful, but source is a press-release rehost; prefer a primary or trade-source URL before posting.",
            "- `watch_only`: relevant enough to monitor, but weaker, medium-confidence, or from a source that should be upgraded before posting.",
            "",
            "## Query Packs",
            "",
        ]
    )
    for pack in result.query_packs:
        lines.extend(
            [
                f"- `{pack.id}`: {pack.goal}",
            ]
        )

    lines.extend(["", "## New Candidates For Review", ""])
    if result.accepted_candidates:
        for index, evaluated in enumerate(result.accepted_candidates, start=1):
            candidate = evaluated.candidate
            lines.extend(
                [
                    _candidate_line(index, evaluated),
                    f"   Signal: {_safe(candidate.matched_signal) or '-'}",
                    f"   Why relevant: {_safe(candidate.why_relevant) or '-'}",
                    f"   Summary: {_safe(candidate.summary) or '-'}",
                    "",
                ]
            )
    else:
        lines.append("No new candidates passed URL dedupe and confidence gating.")

    skipped = [item for item in result.evaluated_candidates if not item.accepted_for_review]
    lines.extend(["", "## Skipped Candidates", ""])
    if skipped:
        for index, evaluated in enumerate(skipped, start=1):
            candidate = evaluated.candidate
            dedupe = evaluated.dedupe
            reason = evaluated.rejection_reason or dedupe.reason or "not accepted"
            if dedupe.match is not None:
                reason = f"{reason}; matched {dedupe.match.table_name}"
                if dedupe.match.title:
                    reason = f"{reason}: {dedupe.match.title}"
            lines.extend(
                [
                    _candidate_line(index, evaluated),
                    f"   Skip reason: {reason}",
                    "",
                ]
            )
    else:
        lines.append("No skipped candidates.")

    lines.extend(["", "## Raw Discovery Response", "", "```json", result.raw_response_text.strip(), "```", ""])
    return "\n".join(lines)


def write_discovery_outputs(result: DiscoveryRunResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.generated_at.strftime("%Y%m%dT%H%M%SZ")
    markdown_path = output_dir / f"web-discovery-{stamp}.md"
    json_path = output_dir / f"web-discovery-{stamp}.json"
    markdown_path.write_text(build_discovery_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, default=_json_default, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return markdown_path, json_path


def write_discovery_failure_report(output_dir: Path, *, error: BaseException) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    markdown_path = output_dir / f"web-discovery-failed-{stamp}.md"
    error_text = str(error)
    markdown_path.write_text(
        "\n".join(
            [
                "# Daily Web Discovery Failed",
                "",
                f"Generated at: `{generated_at.isoformat()}`",
                f"Error type: `{type(error).__name__}`",
                f"Error: `{error_text}`",
                "",
                "The discovery provider did not return a usable response. No candidates were ingested or sent.",
                "Retry manually with a smaller `max_search_uses` value or a higher `WEB_DISCOVERY_TIMEOUT_SECONDS`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return markdown_path
