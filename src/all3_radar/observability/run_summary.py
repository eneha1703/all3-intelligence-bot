"""Run summary formatting helpers."""

from __future__ import annotations

from all3_radar.domain.models import RadarRunResult


def format_radar_run_summary(result: RadarRunResult) -> str:
    return (
        f"run_id={result.run_id} "
        f"sources={result.selected_sources} "
        f"collected={result.collected_items} "
        f"normalized={result.normalized_items} "
        f"fresh={result.fresh_items} "
        f"stale={result.stale_items} "
        f"missing_published_ts={result.missing_published_ts} "
        f"unsupported_sources={result.unsupported_sources}"
    )
