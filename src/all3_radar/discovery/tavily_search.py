"""Tavily-backed daily discovery with Claude review."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from all3_radar.discovery.claude_web_search import _extract_json_object, _normalize_text, _parse_candidates
from all3_radar.discovery.models import (
    DiscoveryCandidate,
    DiscoveryClientResult,
    DiscoveryQueryPack,
    DiscoveryRuntimeConfig,
)


class TavilyWebDiscoveryUnavailableError(RuntimeError):
    """Raised when Tavily-backed web discovery is unavailable or malformed."""


def _freshness_window_label(*, generated_at: datetime, freshness_days: int) -> str:
    start = (generated_at - timedelta(days=freshness_days)).date().isoformat()
    end = generated_at.date().isoformat()
    return f"{start} through {end}"


def _iter_search_plan(
    query_packs: tuple[DiscoveryQueryPack, ...],
    *,
    max_search_uses: int,
) -> list[tuple[DiscoveryQueryPack, str]]:
    plan: list[tuple[DiscoveryQueryPack, str]] = []
    round_index = 0
    while len(plan) < max_search_uses:
        added_any = False
        for pack in query_packs:
            if round_index < len(pack.queries):
                plan.append((pack, pack.queries[round_index]))
                added_any = True
                if len(plan) >= max_search_uses:
                    break
        if not added_any:
            break
        round_index += 1
    return plan


def _pack_payload(pack: DiscoveryQueryPack) -> dict[str, Any]:
    return {
        "id": pack.id,
        "name": pack.name,
        "goal": pack.goal,
        "include_signals": list(pack.include_signals),
        "exclude_signals": list(pack.exclude_signals),
    }


def build_tavily_review_prompt(
    *,
    query_packs: tuple[DiscoveryQueryPack, ...],
    search_batches: list[dict[str, Any]],
    freshness_days: int,
    max_candidates: int,
    generated_at: datetime | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    window_label = _freshness_window_label(generated_at=generated_at, freshness_days=freshness_days)
    payload = {
        "generated_at_utc": generated_at.isoformat(),
        "freshness_days": freshness_days,
        "freshness_window": window_label,
        "max_candidates": max_candidates,
        "query_packs": [_pack_payload(pack) for pack in query_packs],
        "search_batches": search_batches,
    }
    return (
        "You are reviewing Tavily web-search results for All3's daily web discovery. "
        "Tavily has already searched the web. Your job is to choose only fresh, concrete articles from the provided results. "
        "Do not invent URLs, dates, source names, or facts. "
        "Only use articles present in search_batches. "
        f"For this run, the freshness window is {window_label}. "
        "If no article in a query pack is fresh enough and specific enough, return no candidate for that pack. "
        "Do not substitute older relevant stories, explainers, reports, rankings, guides, market overviews, application pages, or evergreen content. "
        "Treat query packs as editorial search briefs, not broad themes. "
        "Select articles only when they match an include signal with a concrete operational, market, deployment, capacity, adoption, funding, productivity, policy, or delivery-system angle relevant to All3. "
        "Prefer primary sources, reputable trade publications, official statistics, and credible business or technology press. "
        "Use confidence=high only when the result clearly matches the brief and appears fresh from the provided metadata/content. "
        "Use confidence=medium when relevant but slightly weaker. Use confidence=low for borderline items. "
        "Return at most max_candidates total candidates across all packs. "
        "Output only one JSON object. Do not use markdown or code fences. "
        "Start your response with { and end it with }. "
        "Do not include citations, commentary, source lists, or any text outside the JSON object. "
        "Use this exact schema: "
        '{"candidates":[{"title":string,"url":string,"source_name":string|null,"published_date":string|null,'
        '"summary":string|null,"query_pack_id":string,"matched_signal":string|null,'
        '"why_relevant":string|null,"confidence":"low|medium|high"}]}. '
        "Do not include duplicate URLs in the response.\n\n"
        f"Discovery review JSON:\n{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


@dataclass(frozen=True)
class TavilyWebDiscoveryClient:
    runtime_config: DiscoveryRuntimeConfig

    @property
    def is_available(self) -> bool:
        return bool(self.runtime_config.search_api_key and self.runtime_config.api_key and self.runtime_config.model)

    def discover(
        self,
        *,
        query_packs: tuple[DiscoveryQueryPack, ...],
        freshness_days: int,
    ) -> DiscoveryClientResult:
        if not self.runtime_config.search_api_key:
            raise TavilyWebDiscoveryUnavailableError("TAVILY_API_KEY is not configured.")
        if not self.runtime_config.api_key:
            raise TavilyWebDiscoveryUnavailableError("ANTHROPIC_API_KEY is not configured.")
        if not self.runtime_config.model:
            raise TavilyWebDiscoveryUnavailableError("WEB_DISCOVERY_MODEL is not configured.")

        generated_at = datetime.now(timezone.utc)
        search_plan = _iter_search_plan(query_packs, max_search_uses=self.runtime_config.max_search_uses)
        search_batches = [self._search_tavily(pack=pack, query=query, freshness_days=freshness_days) for pack, query in search_plan]
        prompt = build_tavily_review_prompt(
            query_packs=query_packs,
            search_batches=search_batches,
            freshness_days=freshness_days,
            max_candidates=self.runtime_config.max_candidates_returned,
            generated_at=generated_at,
        )
        review_body = self._review_with_claude(prompt)
        text = self._extract_text(review_body)
        try:
            parsed = _extract_json_object(text)
        except RuntimeError as exc:
            raise TavilyWebDiscoveryUnavailableError(
                f"{exc} Raw response preview: {text[:1000]}"
            ) from exc
        candidates = _parse_candidates(parsed, {pack.id for pack in query_packs})
        claude_usage = review_body.get("usage") if isinstance(review_body.get("usage"), dict) else {}
        usage = {
            "tavily_search_batches": [
                {
                    "query_pack_id": batch["query_pack_id"],
                    "query": batch["query"],
                    "result_count": len(batch["results"]),
                }
                for batch in search_batches
            ],
            "claude_usage": claude_usage,
        }
        raw_response_text = json.dumps(
            {
                "tavily_search_batches": search_batches,
                "claude_review_response": text,
            },
            ensure_ascii=False,
            indent=2,
        )
        return DiscoveryClientResult(
            candidates=candidates,
            raw_response_text=raw_response_text,
            web_search_requests=len(search_batches),
            usage=usage,
        )

    def _search_tavily(
        self,
        *,
        pack: DiscoveryQueryPack,
        query: str,
        freshness_days: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "topic": "news",
            "search_depth": self.runtime_config.tavily_search_depth,
            "days": freshness_days,
            "max_results": pack.max_results,
            "include_answer": False,
            "include_images": False,
            "include_favicon": False,
        }
        if self.runtime_config.tavily_include_raw_content:
            payload["include_raw_content"] = "markdown"
        if self.runtime_config.blocked_domains:
            payload["exclude_domains"] = list(self.runtime_config.blocked_domains)
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.runtime_config.search_api_key}",
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
            raise TavilyWebDiscoveryUnavailableError(
                f"Tavily search failed with HTTP {exc.code}: {error_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TavilyWebDiscoveryUnavailableError(f"Tavily search failed: {exc}") from exc
        raw_results = body.get("results")
        if not isinstance(raw_results, list):
            raise TavilyWebDiscoveryUnavailableError("Tavily response did not contain a results list.")
        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue
            url = _normalize_text(raw_result.get("url"))
            title = _normalize_text(raw_result.get("title"))
            if not url or not title:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "source_name": _normalize_text(raw_result.get("source")) or _normalize_text(raw_result.get("source_name")),
                    "published_date": _normalize_text(raw_result.get("published_date")),
                    "content": _normalize_text(raw_result.get("raw_content")) or _normalize_text(raw_result.get("content")),
                    "score": raw_result.get("score"),
                }
            )
        return {
            "query_pack_id": pack.id,
            "query": query,
            "goal": pack.goal,
            "include_signals": list(pack.include_signals),
            "exclude_signals": list(pack.exclude_signals),
            "results": results,
        }

    def _review_with_claude(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.runtime_config.model,
            "max_tokens": self.runtime_config.max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = ""
            raise TavilyWebDiscoveryUnavailableError(
                f"Claude review failed with HTTP {exc.code}: {error_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TavilyWebDiscoveryUnavailableError(f"Claude review failed: {exc}") from exc

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
            raise TavilyWebDiscoveryUnavailableError("Claude review response did not contain text content.") from exc
        if not text:
            raise TavilyWebDiscoveryUnavailableError("Claude review response was empty.")
        return text
