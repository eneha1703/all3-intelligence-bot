"""Config loading and validation utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml

from all3_radar.config.models import AppConfig, DigestConfig, RadarConfig, Settings, TelegramConfig


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing required config key: {key}")
    return mapping[key]


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Expected boolean value, got: {value!r}")


def _parse_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected integer for {field_name}, got: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"Expected non-negative integer for {field_name}, got: {parsed}")
    return parsed


def _apply_env_override(section: Mapping[str, Any], field_name: str, env: Mapping[str, str], env_name: str) -> Any:
    return env.get(env_name, section[field_name])


def load_settings(repo_root: Path, env: Mapping[str, str] | None = None) -> Settings:
    env = env or os.environ
    config = load_yaml(repo_root / "config" / "settings.yaml")

    app = dict(_require(config, "app"))
    radar = dict(_require(config, "radar"))
    digest = dict(_require(config, "digest"))
    telegram = dict(_require(config, "telegram"))

    timezone = str(_apply_env_override(app, "timezone", env, "TIMEZONE"))
    database_value = str(_apply_env_override(app, "database_path", env, "DATABASE_PATH"))
    database_path = Path(database_value)
    if not database_path.is_absolute():
        database_path = repo_root / database_path
    log_level = str(_apply_env_override(app, "log_level", env, "LOG_LEVEL")).upper()

    return Settings(
        app=AppConfig(
            timezone=timezone,
            database_path=database_path,
            log_level=log_level,
        ),
        radar=RadarConfig(
            lookback_hours=_parse_int(radar["lookback_hours"], "radar.lookback_hours"),
            require_published_ts=_parse_bool(radar["require_published_ts"]),
            allow_collected_at_fallback=_parse_bool(
                _apply_env_override(radar, "allow_collected_at_fallback", env, "ALLOW_COLLECTED_AT_FALLBACK")
            ),
            max_cards_per_run=_parse_int(radar["max_cards_per_run"], "radar.max_cards_per_run"),
            shortlist_size_before_gemini=_parse_int(
                radar["shortlist_size_before_gemini"], "radar.shortlist_size_before_gemini"
            ),
            google_competitor_check_enabled=_parse_bool(
                _apply_env_override(radar, "google_competitor_check_enabled", env, "GOOGLE_COMPETITOR_CHECK_ENABLED")
            ),
            google_competitor_send_enabled=_parse_bool(
                _apply_env_override(radar, "google_competitor_send_enabled", env, "GOOGLE_COMPETITOR_SEND_ENABLED")
            ),
        ),
        digest=DigestConfig(
            stories_per_digest=_parse_int(digest["stories_per_digest"], "digest.stories_per_digest"),
            shortlist_size_before_claude=_parse_int(
                digest["shortlist_size_before_claude"], "digest.shortlist_size_before_claude"
            ),
            require_canonical_events=_parse_bool(digest["require_canonical_events"]),
        ),
        telegram=TelegramConfig(
            parse_mode=str(telegram["parse_mode"]),
            disable_web_page_preview=_parse_bool(telegram["disable_web_page_preview"]),
        ),
    )
