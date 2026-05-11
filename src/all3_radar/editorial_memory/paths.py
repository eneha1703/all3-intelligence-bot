"""Path resolution helpers for the editorial memory layer."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_editorial_memory_database_path(repo_root: Path, env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    configured = (env.get("EDITORIAL_MEMORY_DATABASE_PATH") or "data/editorial_memory.db").strip()
    path = Path(configured)
    if not path.is_absolute():
        path = repo_root / path
    return path


def resolve_editorial_memory_rules_path(repo_root: Path) -> Path:
    return repo_root / "config" / "editorial_memory_rules.yaml"


def resolve_editorial_memory_schema_path(repo_root: Path) -> Path:
    return repo_root / "src" / "all3_radar" / "editorial_memory" / "schema.sql"

