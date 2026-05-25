"""Configuration loading for daily web discovery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from all3_radar.config.loader import load_yaml
from all3_radar.discovery.models import DiscoveryConfig, DiscoveryQueryPack, DiscoveryRuntimeConfig

DEFAULT_MODEL = "claude-sonnet-4-20250514"
VALID_DISCOVERY_PROVIDERS = {"claude_web_search", "tavily_search"}


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Expected boolean value, got: {value!r}")


def _parse_int(value: Any, field_name: str, *, default: int, minimum: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected integer for {field_name}, got: {value!r}") from exc
    if parsed < minimum:
        raise ValueError(f"Expected {field_name} >= {minimum}, got: {parsed}")
    return parsed


def _parse_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part).strip() for part in value if str(part).strip())
    raise ValueError(f"Expected string list, got: {value!r}")


def _require_non_empty(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required web discovery field: {field_name}")
    return text


def _parse_query_pack(raw_pack: Mapping[str, Any]) -> DiscoveryQueryPack:
    pack_id = _require_non_empty(raw_pack.get("id"), "query_packs[].id")
    queries = _parse_string_tuple(raw_pack.get("queries"))
    if not queries:
        raise ValueError(f"Web discovery query pack {pack_id!r} must include at least one query.")
    return DiscoveryQueryPack(
        id=pack_id,
        name=_require_non_empty(raw_pack.get("name"), f"query_packs[{pack_id}].name"),
        goal=_require_non_empty(raw_pack.get("goal"), f"query_packs[{pack_id}].goal"),
        include_signals=_parse_string_tuple(raw_pack.get("include_signals")),
        exclude_signals=_parse_string_tuple(raw_pack.get("exclude_signals")),
        queries=queries,
        max_results=_parse_int(raw_pack.get("max_results"), f"query_packs[{pack_id}].max_results", default=5, minimum=1),
    )


def load_discovery_config(path: Path) -> DiscoveryConfig:
    payload = load_yaml(path)
    query_packs = tuple(_parse_query_pack(raw_pack) for raw_pack in payload.get("query_packs", []))
    if not query_packs:
        raise ValueError("Web discovery config must include at least one query pack.")
    provider = str(payload.get("provider") or "tavily_search").strip()
    if provider not in VALID_DISCOVERY_PROVIDERS:
        raise ValueError(f"Unsupported web discovery provider: {provider}")
    return DiscoveryConfig(
        enabled=_parse_bool(payload.get("enabled"), default=True),
        provider=provider,
        freshness_days=_parse_int(payload.get("freshness_days"), "freshness_days", default=3, minimum=1),
        max_search_uses=_parse_int(payload.get("max_search_uses"), "max_search_uses", default=8, minimum=1),
        max_candidates_returned=_parse_int(
            payload.get("max_candidates_returned"),
            "max_candidates_returned",
            default=20,
            minimum=1,
        ),
        max_new_candidates=_parse_int(payload.get("max_new_candidates"), "max_new_candidates", default=12, minimum=1),
        query_packs=query_packs,
    )


def load_discovery_runtime_config(
    discovery_config: DiscoveryConfig,
    env: Mapping[str, str] | None = None,
) -> DiscoveryRuntimeConfig:
    env = env or os.environ
    model = (
        env.get("WEB_DISCOVERY_MODEL")
        or env.get("CLAUDE_EDITORIAL_MODEL")
        or env.get("CLAUDE_FINAL_CARD_MODEL")
        or DEFAULT_MODEL
    ).strip()
    tavily_search_depth = _require_non_empty(
        env.get("WEB_DISCOVERY_TAVILY_SEARCH_DEPTH") or "basic",
        "WEB_DISCOVERY_TAVILY_SEARCH_DEPTH",
    ).lower()
    if tavily_search_depth not in {"basic", "advanced"}:
        raise ValueError(f"WEB_DISCOVERY_TAVILY_SEARCH_DEPTH must be basic or advanced, got: {tavily_search_depth}")
    return DiscoveryRuntimeConfig(
        api_key=env.get("ANTHROPIC_API_KEY") or None,
        search_api_key=env.get("TAVILY_API_KEY") or None,
        model=model or DEFAULT_MODEL,
        timeout_seconds=_parse_int(env.get("WEB_DISCOVERY_TIMEOUT_SECONDS"), "WEB_DISCOVERY_TIMEOUT_SECONDS", default=180, minimum=1),
        max_tokens=_parse_int(env.get("WEB_DISCOVERY_MAX_TOKENS"), "WEB_DISCOVERY_MAX_TOKENS", default=2500, minimum=1),
        max_search_uses=_parse_int(
            env.get("WEB_DISCOVERY_MAX_SEARCH_USES"),
            "WEB_DISCOVERY_MAX_SEARCH_USES",
            default=discovery_config.max_search_uses,
            minimum=1,
        ),
        max_candidates_returned=_parse_int(
            env.get("WEB_DISCOVERY_MAX_CANDIDATES"),
            "WEB_DISCOVERY_MAX_CANDIDATES",
            default=discovery_config.max_candidates_returned,
            minimum=1,
        ),
        max_new_candidates=_parse_int(
            env.get("WEB_DISCOVERY_MAX_NEW_CANDIDATES"),
            "WEB_DISCOVERY_MAX_NEW_CANDIDATES",
            default=discovery_config.max_new_candidates,
            minimum=1,
        ),
        tavily_search_depth=tavily_search_depth,
        tavily_include_raw_content=_parse_bool(env.get("WEB_DISCOVERY_TAVILY_INCLUDE_RAW_CONTENT"), default=True),
        blocked_domains=_parse_string_tuple(env.get("WEB_DISCOVERY_BLOCKED_DOMAINS")),
    )
