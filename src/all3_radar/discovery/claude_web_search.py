"""Claude web-search client for daily discovery."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from all3_radar.discovery.models import (
    DiscoveryCandidate,
    DiscoveryClientResult,
    DiscoveryQueryPack,
    DiscoveryRuntimeConfig,
)

VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}
FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


class ClaudeWebDiscoveryUnavailableError(RuntimeError):
    """Raised when Claude web discovery is unavailable or returns invalid output."""


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = WHITESPACE_RE.sub(" ", str(value)).strip()
    return normalized or None


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            character = text[index]
            if in_string:
                if escape:
                    escape = False
                elif character == "\\":
                    escape = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced_match = FENCED_JSON_RE.search(stripped)
    if fenced_match:
        stripped = fenced_match.group(1).strip()
    elif not stripped.startswith("{"):
        balanced = _extract_balanced_json_object(stripped)
        if balanced is None:
            raise ClaudeWebDiscoveryUnavailableError("Claude discovery response was not valid JSON.")
        stripped = balanced
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ClaudeWebDiscoveryUnavailableError("Claude discovery response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ClaudeWebDiscoveryUnavailableError("Claude discovery response must be a JSON object.")
    return parsed


def _pack_to_prompt_payload(pack: DiscoveryQueryPack) -> dict[str, Any]:
    return {
        "id": pack.id,
        "name": pack.name,
        "goal": pack.goal,
        "include_signals": list(pack.include_signals),
        "exclude_signals": list(pack.exclude_signals),
        "queries": list(pack.queries),
        "max_results": pack.max_results,
    }


def _freshness_window_label(*, generated_at: datetime, freshness_days: int) -> str:
    start = (generated_at - timedelta(days=freshness_days)).date().isoformat()
    end = generated_at.date().isoformat()
    return f"{start} through {end}"


def _fresh_query(query: str, *, generated_at: datetime, freshness_days: int) -> str:
    start = (generated_at - timedelta(days=freshness_days)).date().isoformat()
    month_label = generated_at.strftime("%B %Y")
    return f"{query} after:{start} {month_label}"


def build_discovery_prompt(
    *,
    query_packs: tuple[DiscoveryQueryPack, ...],
    freshness_days: int,
    max_candidates: int,
    generated_at: datetime | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    window_label = _freshness_window_label(generated_at=generated_at, freshness_days=freshness_days)
    pack_payloads = []
    for pack in query_packs:
        pack_payload = _pack_to_prompt_payload(pack)
        pack_payload["fresh_queries"] = [
            _fresh_query(query, generated_at=generated_at, freshness_days=freshness_days)
            for query in pack.queries
        ]
        pack_payloads.append(pack_payload)
    payload = {
        "generated_at_utc": generated_at.isoformat(),
        "freshness_days": freshness_days,
        "freshness_window": window_label,
        "max_candidates": max_candidates,
        "query_packs": pack_payloads,
    }
    return (
        "You are a daily web-discovery analyst for All3's News Radar. "
        "Use web search to find fresh, concrete news outside the bot's fixed source list. "
        "Do not write a digest. Do not invent URLs, dates, numbers, or source names. "
        "Only return articles published within freshness_days of generated_at_utc. "
        f"For this run, the freshness window is {window_label}. "
        "If no article in a query pack is fresh enough, return no candidate for that pack instead of substituting older relevant material. "
        "Use the provided fresh_queries or equivalent searches with explicit date filters. "
        "Try to cover each query pack before spending multiple searches on the same pack. "
        "Do not return older articles, reports, guides, rankings, top-10 lists, evergreen resource pages, or market-overview pages. "
        "Return candidates only when the article has a concrete operational, market, deployment, capacity, adoption, funding, "
        "productivity, policy, or delivery-system signal relevant to All3. "
        "Treat the query packs as editorial search briefs, not broad topics. "
        "Prefer primary sources, reputable trade publications, official statistics, and credible business/technology press. "
        "Avoid generic trend pieces, opinion-only articles, architecture awards, custom-home inspiration, mortgage/rent-only stories, "
        "consumer robot demos, company profile fluff, and broad 2026 trend reports unless there is a concrete event matching an include signal. "
        "Search broadly enough to satisfy the packs, but stay within the max search budget. "
        "Return at most max_candidates total candidates across all packs. "
        "For each candidate, identify the query_pack_id and the specific matched signal. "
        "Use confidence=high only when the article clearly matches the pack and appears fresh. "
        "Use confidence=medium when relevant but not yet proven strong. Use confidence=low for borderline items. "
        "Output only one JSON object. Do not use markdown or code fences. "
        "Start your response with { and end it with }. "
        "Do not include citations, commentary, source lists, or any text outside the JSON object. "
        "Use this exact schema: "
        '{"candidates":[{"title":string,"url":string,"source_name":string|null,"published_date":string|null,'
        '"summary":string|null,"query_pack_id":string,"matched_signal":string|null,'
        '"why_relevant":string|null,"confidence":"low|medium|high"}]}. '
        "Do not include duplicate URLs in the response.\n\n"
        f"Discovery brief JSON:\n{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


def _parse_candidates(parsed: dict[str, Any], allowed_pack_ids: set[str]) -> tuple[DiscoveryCandidate, ...]:
    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ClaudeWebDiscoveryUnavailableError("Claude discovery response must include candidates list.")

    candidates: list[DiscoveryCandidate] = []
    seen_urls: set[str] = set()
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            continue
        title = _normalize_text(raw_candidate.get("title"))
        url = _normalize_text(raw_candidate.get("url"))
        if not title or not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        query_pack_id = _normalize_text(raw_candidate.get("query_pack_id")) or "unknown"
        if query_pack_id not in allowed_pack_ids:
            query_pack_id = "unknown"
        confidence = (_normalize_text(raw_candidate.get("confidence")) or "low").lower()
        if confidence not in VALID_CONFIDENCE_LEVELS:
            confidence = "low"
        candidates.append(
            DiscoveryCandidate(
                title=title,
                url=url,
                source_name=_normalize_text(raw_candidate.get("source_name")),
                published_date=_normalize_text(raw_candidate.get("published_date")),
                summary=_normalize_text(raw_candidate.get("summary")),
                query_pack_id=query_pack_id,
                matched_signal=_normalize_text(raw_candidate.get("matched_signal")),
                why_relevant=_normalize_text(raw_candidate.get("why_relevant")),
                confidence=confidence,
                raw_payload=dict(raw_candidate),
            )
        )
    return tuple(candidates)


@dataclass(frozen=True)
class ClaudeWebDiscoveryClient:
    runtime_config: DiscoveryRuntimeConfig

    @property
    def is_available(self) -> bool:
        return bool(self.runtime_config.api_key and self.runtime_config.model)

    def discover(
        self,
        *,
        query_packs: tuple[DiscoveryQueryPack, ...],
        freshness_days: int,
    ) -> DiscoveryClientResult:
        if not self.runtime_config.api_key:
            raise ClaudeWebDiscoveryUnavailableError("ANTHROPIC_API_KEY is not configured.")
        if not self.runtime_config.model:
            raise ClaudeWebDiscoveryUnavailableError("WEB_DISCOVERY_MODEL is not configured.")

        prompt = build_discovery_prompt(
            query_packs=query_packs,
            freshness_days=freshness_days,
            max_candidates=self.runtime_config.max_candidates_returned,
        )
        tool: dict[str, Any] = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": self.runtime_config.max_search_uses,
        }
        if self.runtime_config.blocked_domains:
            tool["blocked_domains"] = list(self.runtime_config.blocked_domains)
        payload = {
            "model": self.runtime_config.model,
            "max_tokens": self.runtime_config.max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.runtime_config.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.runtime_config.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = ""
            raise ClaudeWebDiscoveryUnavailableError(
                f"Claude web discovery request failed with HTTP {exc.code}: {error_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ClaudeWebDiscoveryUnavailableError(f"Claude web discovery request failed: {exc}") from exc

        text = self._extract_text(body)
        try:
            parsed = _extract_json_object(text)
        except ClaudeWebDiscoveryUnavailableError as exc:
            raise ClaudeWebDiscoveryUnavailableError(
                f"{exc} Raw response preview: {text[:1000]}"
            ) from exc
        candidates = _parse_candidates(parsed, {pack.id for pack in query_packs})
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        server_tool_use = usage.get("server_tool_use") if isinstance(usage.get("server_tool_use"), dict) else {}
        web_search_requests = int(server_tool_use.get("web_search_requests") or 0)
        return DiscoveryClientResult(
            candidates=candidates,
            raw_response_text=text,
            web_search_requests=web_search_requests,
            usage=usage,
        )

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        try:
            content_blocks = body["content"]
            text = "".join(
                block.get("text", "")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
        except (KeyError, TypeError) as exc:
            raise ClaudeWebDiscoveryUnavailableError("Claude response did not contain text content.") from exc
        if not text:
            raise ClaudeWebDiscoveryUnavailableError("Claude response was empty.")
        return text
