"""Typed configuration models for the All3 radar project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    database_path: Path
    log_level: str


@dataclass(frozen=True)
class RadarConfig:
    lookback_hours: int
    require_published_ts: bool
    allow_collected_at_fallback: bool
    max_cards_per_run: int
    shortlist_size_before_gemini: int
    google_competitor_check_enabled: bool
    google_competitor_send_enabled: bool
    claude_final_card_enabled: bool
    claude_final_card_max_candidates: int
    claude_editorial_enabled: bool
    claude_editorial_max_candidates: int


@dataclass(frozen=True)
class DigestConfig:
    stories_per_digest: int
    shortlist_size_before_claude: int
    require_canonical_events: bool
    claude_digest_enabled: bool
    claude_digest_max_input_items: int
    claude_digest_full_text_enabled: bool
    claude_digest_full_text_max_candidates: int
    claude_digest_full_text_max_chars: int
    claude_digest_full_text_timeout_seconds: int


@dataclass(frozen=True)
class TelegramConfig:
    parse_mode: str
    disable_web_page_preview: bool


@dataclass(frozen=True)
class TelegramGroupCurationConfig:
    enabled: bool
    message_ingest_enabled: bool
    reaction_shortlist_enabled: bool
    shortlist_reaction_allowlist: tuple[str, ...]
    shortlist_window_days: int
    shortlist_min_unique_reactors: int


@dataclass(frozen=True)
class IntegrationsConfig:
    gemini_api_key: str | None
    gemini_model: str
    anthropic_api_key: str | None
    claude_digest_model: str | None
    claude_digest_timeout_seconds: int
    claude_digest_max_tokens: int
    claude_final_card_model: str | None
    claude_final_card_timeout_seconds: int
    claude_final_card_max_tokens: int
    claude_editorial_model: str | None
    claude_editorial_timeout_seconds: int
    claude_editorial_max_tokens: int
    telegram_alert_bot_token: str | None
    telegram_alert_chat_ids: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    app: AppConfig
    radar: RadarConfig
    digest: DigestConfig
    telegram: TelegramConfig
    telegram_group_curation: TelegramGroupCurationConfig
    integrations: IntegrationsConfig
