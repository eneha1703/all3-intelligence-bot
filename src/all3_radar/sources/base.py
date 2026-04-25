"""Base source adapter abstractions."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

from all3_radar.domain.models import CollectedRawItem, SourceDefinition

FetchText = Callable[[str], str]


class UnsupportedSourceError(RuntimeError):
    """Raised when a configured source is not implemented in the current slice."""


class SourceAdapter(Protocol):
    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        """Collect raw items for a single source."""
