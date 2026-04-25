"""Google News competitor-check adapter will live here."""

from __future__ import annotations

from datetime import datetime

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import UnsupportedSourceError


class GoogleCompetitorAdapter:
    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        raise UnsupportedSourceError(f"Google competitor source disabled in this slice: {source.id}")
