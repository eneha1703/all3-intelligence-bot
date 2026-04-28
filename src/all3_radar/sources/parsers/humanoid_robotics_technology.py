"""Parser for Humanoid Robotics Technology listing and article pages."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText
from all3_radar.sources.rss import _clean_text, parse_published_timestamp

ARTICLE_PATH_RE = re.compile(r"/industry-news/[^\"'#?]+/?$")
META_TAG_RE = re.compile(r'<meta\s+[^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']+)["\']', re.IGNORECASE)
TIME_TAG_RE = re.compile(r'<time[^>]*datetime=["\']([^"\']+)["\']', re.IGNORECASE)
JSON_LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _extract_external_id(url: str) -> str | None:
    path = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return path or None


class _HrtListingParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.article_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        if ARTICLE_PATH_RE.search(urlparse(absolute).path) and absolute not in self.article_urls:
            self.article_urls.append(absolute)


@dataclass
class ParsedArticle:
    title: str
    published_ts: datetime | None
    snippet: str | None


def _extract_meta_map(article_html: str) -> dict[str, str]:
    return {name.lower(): html.unescape(content).strip() for name, content in META_TAG_RE.findall(article_html)}


def _extract_json_ld_published(article_html: str) -> datetime | None:
    for raw_block in JSON_LD_RE.findall(article_html):
        cleaned = raw_block.strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            date_value = candidate.get("datePublished") or candidate.get("dateCreated")
            if isinstance(date_value, str):
                parsed = parse_published_timestamp(date_value)
                if parsed is not None:
                    return parsed
    return None


def _extract_first_paragraph(article_html: str) -> str | None:
    for match in PARAGRAPH_RE.findall(article_html):
        text = _clean_text(re.sub(r"<[^>]+>", " ", match))
        if text:
            return text
    return None


def parse_humanoid_robotics_article(article_html: str) -> ParsedArticle:
    meta = _extract_meta_map(article_html)
    title = (
        _clean_text(meta.get("og:title"))
        or _clean_text(meta.get("twitter:title"))
        or _clean_text(meta.get("title"))
    )
    if not title:
        h1_match = H1_RE.search(article_html)
        if h1_match:
            title = _clean_text(re.sub(r"<[^>]+>", " ", h1_match.group(1)))
    if not title:
        raise ValueError("HRT article parser could not extract a title")

    published_ts = None
    for key in ("article:published_time", "og:published_time", "publish-date", "date"):
        candidate = meta.get(key)
        if candidate:
            published_ts = parse_published_timestamp(candidate)
            if published_ts is not None:
                break
    if published_ts is None:
        time_match = TIME_TAG_RE.search(article_html)
        if time_match:
            published_ts = parse_published_timestamp(time_match.group(1))
    if published_ts is None:
        published_ts = _extract_json_ld_published(article_html)

    description = (
        _clean_text(meta.get("description"))
        or _clean_text(meta.get("og:description"))
        or _extract_first_paragraph(article_html)
    )

    return ParsedArticle(title=title, published_ts=published_ts, snippet=description)


def parse_humanoid_robotics_listing(
    listing_html: str,
    source: SourceDefinition,
    collected_at: datetime,
    fetch_text_fn: FetchText,
) -> list[CollectedRawItem]:
    parser = _HrtListingParser(base_url=source.url)
    parser.feed(listing_html)
    parser.close()

    article_limit = int(source.extra_config.get("article_limit", 20))
    items: list[CollectedRawItem] = []
    skipped_missing_dates = 0

    for article_url in parser.article_urls[:article_limit]:
        article_html = fetch_text_fn(article_url)
        parsed = parse_humanoid_robotics_article(article_html)
        if parsed.published_ts is None:
            skipped_missing_dates += 1
            continue

        items.append(
            CollectedRawItem(
                source_id=source.id,
                url=article_url,
                title=parsed.title,
                snippet=parsed.snippet,
                author=None,
                published_ts=parsed.published_ts,
                collected_ts=collected_at,
                external_id=_extract_external_id(article_url),
                raw_payload={
                    "url": article_url,
                    "title": parsed.title,
                    "source_url": source.url,
                },
            )
        )

    if not items:
        if skipped_missing_dates:
            raise ValueError(
                f"HRT parser found article links but could not extract trustworthy published dates: skipped={skipped_missing_dates}"
            )
        raise ValueError("HRT parser did not extract any usable article items")

    return items
