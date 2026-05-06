from pathlib import Path

import pytest

from all3_radar.config.loader import load_settings


def test_load_settings_applies_env_overrides() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "DATABASE_PATH": "data/test_override.db",
            "LOG_LEVEL": "debug",
            "ALLOW_COLLECTED_AT_FALLBACK": "true",
            "GOOGLE_COMPETITOR_CHECK_ENABLED": "false",
            "CLAUDE_FINAL_CARD_ENABLED": "true",
            "CLAUDE_FINAL_CARD_MAX_CANDIDATES": "5",
            "CLAUDE_EDITORIAL_ENABLED": "true",
            "CLAUDE_EDITORIAL_MAX_CANDIDATES": "4",
            "CLAUDE_DIGEST_ENABLED": "true",
            "CLAUDE_DIGEST_MAX_INPUT_ITEMS": "9",
            "CLAUDE_DIGEST_MODEL": "claude-test",
            "CLAUDE_DIGEST_TIMEOUT_SECONDS": "17",
            "CLAUDE_DIGEST_MAX_TOKENS": "999",
            "CLAUDE_FINAL_CARD_MODEL": "claude-final-test",
            "CLAUDE_FINAL_CARD_TIMEOUT_SECONDS": "13",
            "CLAUDE_FINAL_CARD_MAX_TOKENS": "333",
            "CLAUDE_EDITORIAL_MODEL": "claude-editorial-test",
            "CLAUDE_EDITORIAL_TIMEOUT_SECONDS": "31",
            "CLAUDE_EDITORIAL_MAX_TOKENS": "701",
            "TELEGRAM_ALERT_CHAT_IDS": "1,2, 3",
            "TELEGRAM_GROUP_CURATION_ENABLED": "true",
            "TELEGRAM_GROUP_MESSAGE_INGEST_ENABLED": "true",
            "TELEGRAM_REACTION_SHORTLIST_ENABLED": "true",
            "TELEGRAM_SHORTLIST_REACTION_ALLOWLIST": "emoji:star, emoji:fire",
            "TELEGRAM_SHORTLIST_WINDOW_DAYS": "14",
            "TELEGRAM_SHORTLIST_MIN_UNIQUE_REACTORS": "2",
        },
    )

    assert settings.app.database_path == repo_root / "data" / "test_override.db"
    assert settings.app.log_level == "DEBUG"
    assert settings.radar.allow_collected_at_fallback is True
    assert settings.radar.google_competitor_check_enabled is False
    assert settings.radar.claude_final_card_enabled is True
    assert settings.radar.claude_final_card_max_candidates == 5
    assert settings.radar.claude_editorial_enabled is True
    assert settings.radar.claude_editorial_max_candidates == 4
    assert settings.digest.claude_digest_enabled is True
    assert settings.digest.claude_digest_max_input_items == 9
    assert settings.integrations.claude_digest_model == "claude-test"
    assert settings.integrations.claude_digest_timeout_seconds == 17
    assert settings.integrations.claude_digest_max_tokens == 999
    assert settings.integrations.claude_final_card_model == "claude-final-test"
    assert settings.integrations.claude_final_card_timeout_seconds == 13
    assert settings.integrations.claude_final_card_max_tokens == 333
    assert settings.integrations.claude_editorial_model == "claude-editorial-test"
    assert settings.integrations.claude_editorial_timeout_seconds == 31
    assert settings.integrations.claude_editorial_max_tokens == 701
    assert settings.integrations.telegram_alert_chat_ids == ("1", "2", "3")
    assert settings.telegram_group_curation.enabled is True
    assert settings.telegram_group_curation.message_ingest_enabled is True
    assert settings.telegram_group_curation.reaction_shortlist_enabled is True
    assert settings.telegram_group_curation.shortlist_reaction_allowlist == ("emoji:star", "emoji:fire")
    assert settings.telegram_group_curation.shortlist_window_days == 14
    assert settings.telegram_group_curation.shortlist_min_unique_reactors == 2


def test_load_settings_telegram_group_curation_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(repo_root, env={})

    assert settings.telegram_group_curation.enabled is False
    assert settings.telegram_group_curation.message_ingest_enabled is False
    assert settings.telegram_group_curation.reaction_shortlist_enabled is False
    assert settings.telegram_group_curation.shortlist_reaction_allowlist == ("emoji:star",)
    assert settings.telegram_group_curation.shortlist_window_days == 7
    assert settings.telegram_group_curation.shortlist_min_unique_reactors == 1


def test_empty_claude_digest_integer_envs_use_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "CLAUDE_DIGEST_MAX_INPUT_ITEMS": "",
            "CLAUDE_DIGEST_TIMEOUT_SECONDS": "",
            "CLAUDE_DIGEST_MAX_TOKENS": "",
        },
    )

    assert settings.digest.claude_digest_max_input_items == 12
    assert settings.integrations.claude_digest_timeout_seconds == 20
    assert settings.integrations.claude_digest_max_tokens == 1200


def test_empty_claude_final_card_integer_envs_use_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "CLAUDE_FINAL_CARD_MAX_CANDIDATES": "",
            "CLAUDE_FINAL_CARD_TIMEOUT_SECONDS": "",
            "CLAUDE_FINAL_CARD_MAX_TOKENS": "",
        },
    )

    assert settings.radar.claude_final_card_max_candidates == 10
    assert settings.integrations.claude_final_card_timeout_seconds == 12
    assert settings.integrations.claude_final_card_max_tokens == 300


def test_load_settings_claude_editorial_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(repo_root, env={})

    assert settings.radar.claude_editorial_enabled is False
    assert settings.radar.claude_editorial_max_candidates == 6
    assert settings.integrations.claude_editorial_model == "claude-3-5-sonnet-latest"
    assert settings.integrations.claude_editorial_timeout_seconds == 30
    assert settings.integrations.claude_editorial_max_tokens == 700


def test_empty_claude_editorial_envs_use_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "CLAUDE_EDITORIAL_MODEL": "",
            "CLAUDE_EDITORIAL_MAX_CANDIDATES": "",
            "CLAUDE_EDITORIAL_TIMEOUT_SECONDS": "",
            "CLAUDE_EDITORIAL_MAX_TOKENS": "",
        },
    )

    assert settings.radar.claude_editorial_max_candidates == 6
    assert settings.integrations.claude_editorial_model == "claude-3-5-sonnet-latest"
    assert settings.integrations.claude_editorial_timeout_seconds == 30
    assert settings.integrations.claude_editorial_max_tokens == 700


def test_whitespace_claude_editorial_envs_use_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "CLAUDE_EDITORIAL_MODEL": "   ",
            "CLAUDE_EDITORIAL_MAX_CANDIDATES": "   ",
            "CLAUDE_EDITORIAL_TIMEOUT_SECONDS": " \t ",
            "CLAUDE_EDITORIAL_MAX_TOKENS": "  ",
        },
    )

    assert settings.radar.claude_editorial_max_candidates == 6
    assert settings.integrations.claude_editorial_model == "claude-3-5-sonnet-latest"
    assert settings.integrations.claude_editorial_timeout_seconds == 30
    assert settings.integrations.claude_editorial_max_tokens == 700


def test_whitespace_claude_digest_integer_envs_use_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "CLAUDE_DIGEST_MAX_INPUT_ITEMS": "   ",
            "CLAUDE_DIGEST_TIMEOUT_SECONDS": " \t ",
            "CLAUDE_DIGEST_MAX_TOKENS": "  ",
        },
    )

    assert settings.digest.claude_digest_max_input_items == 12
    assert settings.integrations.claude_digest_timeout_seconds == 20
    assert settings.integrations.claude_digest_max_tokens == 1200


def test_whitespace_claude_final_card_integer_envs_use_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root,
        env={
            "CLAUDE_FINAL_CARD_MAX_CANDIDATES": "   ",
            "CLAUDE_FINAL_CARD_TIMEOUT_SECONDS": " \t ",
            "CLAUDE_FINAL_CARD_MAX_TOKENS": "  ",
        },
    )

    assert settings.radar.claude_final_card_max_candidates == 10
    assert settings.integrations.claude_final_card_timeout_seconds == 12
    assert settings.integrations.claude_final_card_max_tokens == 300


@pytest.mark.parametrize(
    ("env_name", "value", "expected_field"),
    (
        ("CLAUDE_DIGEST_MAX_INPUT_ITEMS", "abc", "digest.claude_digest_max_input_items"),
        ("CLAUDE_DIGEST_TIMEOUT_SECONDS", "abc", "integrations.claude_digest_timeout_seconds"),
        ("CLAUDE_DIGEST_MAX_TOKENS", "abc", "integrations.claude_digest_max_tokens"),
        ("CLAUDE_FINAL_CARD_MAX_CANDIDATES", "abc", "radar.claude_final_card_max_candidates"),
        ("CLAUDE_FINAL_CARD_TIMEOUT_SECONDS", "abc", "integrations.claude_final_card_timeout_seconds"),
        ("CLAUDE_FINAL_CARD_MAX_TOKENS", "abc", "integrations.claude_final_card_max_tokens"),
        ("CLAUDE_EDITORIAL_MAX_CANDIDATES", "abc", "radar.claude_editorial_max_candidates"),
        ("CLAUDE_EDITORIAL_TIMEOUT_SECONDS", "abc", "integrations.claude_editorial_timeout_seconds"),
        ("CLAUDE_EDITORIAL_MAX_TOKENS", "abc", "integrations.claude_editorial_max_tokens"),
    ),
)
def test_invalid_non_empty_claude_digest_integer_envs_still_raise(
    env_name: str, value: str, expected_field: str
) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    with pytest.raises(ValueError, match=expected_field):
        load_settings(repo_root, env={env_name: value})
