"""Wood Central API adapter implementation."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urljoin

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText, UnsupportedSourceError
from all3_radar.sources.rss import _clean_text, fetch_text, parse_published_timestamp


def _extract_rendered_text(value: object) -> str | None:
    if isinstance(value, dict):
        rendered = value.get("rendered")
        if isinstance(rendered, str):
            return _clean_text(rendered)
    if isinstance(value, str):
        return _clean_text(value)
    return None


def _extract_link(payload: dict, source: SourceDefinition) -> str | None:
    link = payload.get("link")
    if isinstance(link, str) and link.strip():
        return link.strip()

    slug = payload.get("slug")
    if isinstance(slug, str) and slug.strip():
        return urljoin(source.url.rstrip("/") + "/", slug.strip().lstrip("/"))
    return None


def _extract_external_id(payload: dict) -> str | None:
    identifier = payload.get("id")
    if identifier is None:
        return None
    return str(identifier)


def parse_wood_central_posts(feed_text: str, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
    try:
        payload = json.loads(feed_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Wood Central API returned invalid JSON: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError("Wood Central API payload is not a post list")

    items: list[CollectedRawItem] = []
    for post in payload:
        if not isinstance(post, dict):
            continue

        title = _extract_rendered_text(post.get("title"))
        url = _extract_link(post, source)
        if not title or not url:
            continue

        published_ts = parse_published_timestamp(
            post.get("date_gmt") if isinstance(post.get("date_gmt"), str) and post.get("date_gmt") else post.get("date")
        )
        snippet = _extract_rendered_text(post.get("excerpt"))

        items.append(
            CollectedRawItem(
                source_id=source.id,
                url=url,
                title=title,
                snippet=snippet,
                author=None,
                published_ts=published_ts,
                collected_ts=collected_at,
                external_id=_extract_external_id(post),
                raw_payload={
                    "id": post.get("id"),
                    "slug": post.get("slug"),
                    "status": post.get("status"),
                    "link": url,
                    "date": post.get("date"),
                    "date_gmt": post.get("date_gmt"),
                    "source_url": source.url,
                },
            )
        )

    if not items:
        raise ValueError("Wood Central API did not return any usable posts")

    return items


class WoodCentralApiAdapter:
    def __init__(self, fetch_text_fn: FetchText | None = None) -> None:
        self._fetch_text = fetch_text_fn or fetch_text

    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        if source.parser != "wood_central_api":
            raise UnsupportedSourceError(f"API source parser not implemented yet: {source.parser}")

        api_path = str(source.extra_config.get("api_path", "/wp-json/wp/v2/posts?per_page=20"))
        api_url = urljoin(source.url.rstrip("/") + "/", api_path.lstrip("/"))
        feed_text = self._fetch_text(api_url)
        return parse_wood_central_posts(feed_text=feed_text, source=source, collected_at=collected_at)
