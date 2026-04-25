"""Shared enums for pipeline state."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10-friendly string enum."""


class SourceKind(StrEnum):
    RSS = "rss"
    LISTING = "listing"
    API = "api"
    GOOGLE_COMPETITOR = "google_competitor"


class SourceLayer(StrEnum):
    DIRECT = "direct"
    GOOGLE_COMPETITOR = "google_competitor"


class PipelineName(StrEnum):
    RADAR = "radar"
    DIGEST = "digest"


class PipelineStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING_PUBLISHED_TS = "missing_published_ts"
