from pathlib import Path

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
            "CLAUDE_DIGEST_ENABLED": "true",
            "CLAUDE_DIGEST_MAX_INPUT_ITEMS": "9",
            "CLAUDE_DIGEST_MODEL": "claude-test",
            "CLAUDE_DIGEST_TIMEOUT_SECONDS": "17",
            "CLAUDE_DIGEST_MAX_TOKENS": "999",
            "TELEGRAM_ALERT_CHAT_IDS": "1,2, 3",
        },
    )

    assert settings.app.database_path == repo_root / "data" / "test_override.db"
    assert settings.app.log_level == "DEBUG"
    assert settings.radar.allow_collected_at_fallback is True
    assert settings.radar.google_competitor_check_enabled is False
    assert settings.digest.claude_digest_enabled is True
    assert settings.digest.claude_digest_max_input_items == 9
    assert settings.integrations.claude_digest_model == "claude-test"
    assert settings.integrations.claude_digest_timeout_seconds == 17
    assert settings.integrations.claude_digest_max_tokens == 999
    assert settings.integrations.telegram_alert_chat_ids == ("1", "2", "3")
