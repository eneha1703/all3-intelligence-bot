"""Wood Central API adapter will live here."""

from __future__ import annotations

from datetime import datetime

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import UnsupportedSourceError


class WoodCentralApiAdapter:
    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        raise UnsupportedSourceError(f"API source not implemented yet: {source.id}")
