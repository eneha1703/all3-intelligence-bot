"""Strict published-date freshness checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from all3_radar.domain.enums import FreshnessStatus
from all3_radar.domain.models import FreshnessEvaluation


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_freshness(
    published_ts: datetime | None,
    collected_ts: datetime,
    now: datetime,
    lookback_hours: int,
    require_published_ts: bool,
    allow_collected_at_fallback: bool,
) -> FreshnessEvaluation:
    now_utc = _to_utc(now)
    collected_utc = _to_utc(collected_ts)
    lower_bound = now_utc - timedelta(hours=lookback_hours)

    if published_ts is None:
        if require_published_ts and not allow_collected_at_fallback:
            return FreshnessEvaluation(
                status=FreshnessStatus.MISSING_PUBLISHED_TS,
                is_fresh=False,
                reason="Missing published timestamp.",
            )
        if collected_utc >= lower_bound:
            return FreshnessEvaluation(
                status=FreshnessStatus.FRESH,
                is_fresh=True,
                reason="Published timestamp missing; collected_at fallback accepted.",
            )
        return FreshnessEvaluation(
            status=FreshnessStatus.STALE,
            is_fresh=False,
            reason="Published timestamp missing and collected_at fallback is outside the freshness window.",
        )

    published_utc = _to_utc(published_ts)
    if lower_bound <= published_utc <= now_utc:
        return FreshnessEvaluation(
            status=FreshnessStatus.FRESH,
            is_fresh=True,
            reason="Published timestamp is inside the freshness window.",
        )

    return FreshnessEvaluation(
        status=FreshnessStatus.STALE,
        is_fresh=False,
        reason="Published timestamp is outside the freshness window.",
    )
