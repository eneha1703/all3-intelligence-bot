"""Load and expose the explicit source inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from all3_radar.config.loader import load_yaml
from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition


def _parse_source_kind(value: str) -> SourceKind:
    try:
        return SourceKind(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported source kind: {value}") from exc


def _parse_source_layer(value: str) -> SourceLayer:
    try:
        return SourceLayer(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported source layer: {value}") from exc


def _build_source_definition(payload: dict) -> SourceDefinition:
    required_fields = {
        "id",
        "name",
        "kind",
        "layer",
        "is_direct_source",
        "is_wrapper",
        "enabled",
        "parser",
        "url",
        "priority",
    }
    missing = sorted(required_fields - set(payload))
    if missing:
        raise ValueError(f"Missing required source fields for {payload.get('id', '<unknown>')}: {', '.join(missing)}")

    extra_config = {key: value for key, value in payload.items() if key not in required_fields and key != "tags"}
    return SourceDefinition(
        id=str(payload["id"]),
        name=str(payload["name"]),
        kind=_parse_source_kind(str(payload["kind"])),
        layer=_parse_source_layer(str(payload["layer"])),
        is_direct_source=bool(payload["is_direct_source"]),
        is_wrapper=bool(payload["is_wrapper"]),
        enabled=bool(payload["enabled"]),
        parser=str(payload["parser"]),
        url=str(payload["url"]),
        priority=int(payload["priority"]),
        tags=tuple(str(tag) for tag in payload.get("tags", [])),
        extra_config=extra_config,
    )


@dataclass(frozen=True)
class SourceRegistry:
    sources: tuple[SourceDefinition, ...]

    def all(self) -> tuple[SourceDefinition, ...]:
        return self.sources

    def get(self, source_id: str) -> SourceDefinition:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(f"Unknown source id: {source_id}")

    def enabled(self) -> tuple[SourceDefinition, ...]:
        return tuple(source for source in self.sources if source.enabled)

    def direct_sources(self) -> tuple[SourceDefinition, ...]:
        return tuple(source for source in self.enabled() if source.is_direct_source)

    def selected(self, source_id: str | None = None) -> tuple[SourceDefinition, ...]:
        if source_id:
            source = self.get(source_id)
            return (source,) if source.enabled and source.is_direct_source else ()
        return self.direct_sources()

    def unsupported_first_slice(self, sources: Iterable[SourceDefinition]) -> tuple[SourceDefinition, ...]:
        return tuple(source for source in sources if not source.supports_first_slice)


def load_source_registry(path: Path) -> SourceRegistry:
    config = load_yaml(path)
    raw_sources = config.get("sources", [])
    return SourceRegistry(tuple(_build_source_definition(raw_source) for raw_source in raw_sources))
