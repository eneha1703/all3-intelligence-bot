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
        },
    )

    assert settings.app.database_path == repo_root / "data" / "test_override.db"
    assert settings.app.log_level == "DEBUG"
    assert settings.radar.allow_collected_at_fallback is True
    assert settings.radar.google_competitor_check_enabled is False
