"""Report writing for web discovery runs."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from all3_radar.discovery.models import DiscoveryRunResult, EvaluatedDiscoveryCandidate

SEARCH_COST_USD = 0.01


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _safe(value: str | None) -> str:
    return (value or "").replace("\n", " ").strip()


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
    return f"{line}\n   " + " | ".join(details)


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
        "## Query Packs",
        "",
    ]
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

    lines.extend(["", "## Raw Claude Response", "", "```json", result.raw_response_text.strip(), "```", ""])
    return "\n".join(lines)


def write_discovery_outputs(result: DiscoveryRunResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.generated_at.strftime("%Y%m%dT%H%M%SZ")
    markdown_path = output_dir / f"web-discovery-{stamp}.md"
    json_path = output_dir / f"web-discovery-{stamp}.json"
    markdown_path.write_text(build_discovery_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, default=_json_default, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return markdown_path, json_path
