"""Load and expose the explicit source inventory."""

from __future__ import annotations

from pathlib import Path

from all3_radar.config.loader import load_yaml


def load_source_registry(path: Path) -> list[dict]:
    config = load_yaml(path)
    return config.get("sources", [])
