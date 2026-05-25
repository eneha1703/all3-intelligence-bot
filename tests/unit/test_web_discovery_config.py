from pathlib import Path

from all3_radar.discovery.config import load_discovery_config, load_discovery_runtime_config


def test_load_web_discovery_config_query_packs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = load_discovery_config(repo_root / "config" / "web_discovery.yaml")

    assert config.enabled is True
    assert config.provider == "claude_web_search"
    assert config.freshness_days == 2
    assert config.max_search_uses == 8
    assert len(config.query_packs) >= 5
    pack_ids = {pack.id for pack in config.query_packs}
    assert "competitor_activity" in pack_ids
    assert "construction_robotics_deployment" in pack_ids
    assert "industrialized_housing_systems" in pack_ids
    assert "housing_delivery_bottlenecks" in pack_ids
    assert "industrial_robotics_physical_ai" in pack_ids


def test_load_web_discovery_runtime_env_overrides() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = load_discovery_config(repo_root / "config" / "web_discovery.yaml")
    runtime = load_discovery_runtime_config(
        config,
        env={
            "ANTHROPIC_API_KEY": "test-key",
            "WEB_DISCOVERY_MODEL": "claude-test",
            "WEB_DISCOVERY_MAX_SEARCH_USES": "4",
            "WEB_DISCOVERY_MAX_CANDIDATES": "11",
            "WEB_DISCOVERY_MAX_NEW_CANDIDATES": "6",
            "WEB_DISCOVERY_TIMEOUT_SECONDS": "33",
            "WEB_DISCOVERY_MAX_TOKENS": "1234",
            "WEB_DISCOVERY_BLOCKED_DOMAINS": "example.com, spam.test",
        },
    )

    assert runtime.api_key == "test-key"
    assert runtime.model == "claude-test"
    assert runtime.max_search_uses == 4
    assert runtime.max_candidates_returned == 11
    assert runtime.max_new_candidates == 6
    assert runtime.timeout_seconds == 33
    assert runtime.max_tokens == 1234
    assert runtime.blocked_domains == ("example.com", "spam.test")
