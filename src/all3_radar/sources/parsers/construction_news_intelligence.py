"""Parser for Construction News Intelligence listing and article pages."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText
from all3_radar.sources.rss import _clean_text, parse_published_timestamp

ARTICLE_PATH_RE = re.compile(r"^/(?:cn-intelligence|sections/data|contracts)/[^?#]+/?$")
EXCLUDED_PATH_RE = re.compile(
    r"^/(?:cn-intelligence/?|cn-intelligence/sector/?|sections/?|sections/data/?|contracts/?|subscribe/?|about-us/?|ai-search/?)$"
)
META_TAG_RE = re.compile(
    r'<meta\s+[^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TIME_TAG_RE = re.compile(r'<time[^>]*datetime=["\']([^"\']+)["\']', re.IGNORECASE)
DATE_LINE_RE = re.compile(r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b")
PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
BOILERPLATE_SNIPPET_TERMS = (
    "this area is reserved",
    "subscribe today",
    "welcome.",
    "to continue reading",
    "log in",
    "register for guest access",
    "already have an account",
    "comments off",
    "leave a comment",
)


class _ConstructionNewsListingParser(HTMLParser):
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
        _append_article_url(self.article_urls, self.base_url, href)


def _append_article_url(article_urls: list[str], base_url: str, href: str) -> None:
    absolute = urljoin(base_url, href)
    path = urlparse(absolute).path
    if EXCLUDED_PATH_RE.match(path):
        return
    if ARTICLE_PATH_RE.match(path) and absolute not in article_urls:
        article_urls.append(absolute)


def _extract_article_urls_from_listing_html(listing_html: str, base_url: str) -> list[str]:
    parser = _ConstructionNewsListingParser(base_url=base_url)
    parser.feed(listing_html)
    parser.close()
    return parser.article_urls


@dataclass(frozen=True)
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


def _extract_date_line(article_html: str) -> datetime | None:
    match = DATE_LINE_RE.search(article_html)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_first_meaningful_paragraph(article_html: str) -> str | None:
    for match in PARAGRAPH_RE.findall(article_html):
        text = _clean_text(re.sub(r"<[^>]+>", " ", match))
        if not text:
            continue
        lowered = text.lower()
        if any(term in lowered for term in BOILERPLATE_SNIPPET_TERMS):
            continue
        return text
    return None


def parse_construction_news_article(article_html: str) -> ParsedArticle:
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
        raise ValueError("Construction News parser could not extract a title")

    published_ts = None
    for key in ("article:published_time", "og:published_time", "date", "publish-date"):
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
    if published_ts is None:
        published_ts = _extract_date_line(article_html)

    snippet = (
        _clean_text(meta.get("description"))
        or _clean_text(meta.get("og:description"))
        or _extract_first_meaningful_paragraph(article_html)
    )
    return ParsedArticle(title=title, published_ts=published_ts, snippet=snippet)


def parse_construction_news_listing(
    listing_html: str,
    source: SourceDefinition,
    collected_at: datetime,
    fetch_text_fn: FetchText,
) -> list[CollectedRawItem]:
    listing_urls = [source.url, *tuple(str(url) for url in source.extra_config.get("listing_urls", ()))]
    article_urls: list[str] = []
    for listing_url in listing_urls:
        current_html = listing_html if listing_url == source.url else fetch_text_fn(listing_url)
        for article_url in _extract_article_urls_from_listing_html(current_html, listing_url):
            if article_url not in article_urls:
                article_urls.append(article_url)

    article_limit = int(source.extra_config.get("article_limit", 20))
    items: list[CollectedRawItem] = []
    skipped_missing_dates = 0

    for article_url in article_urls[:article_limit]:
        article_html = fetch_text_fn(article_url)
        parsed = parse_construction_news_article(article_html)
        if parsed.published_ts is None:
            skipped_missing_dates += 1
            continue
        external_id = urlparse(article_url).path.rstrip("/").rsplit("/", 1)[-1] or None
        items.append(
            CollectedRawItem(
                source_id=source.id,
                url=article_url,
                title=parsed.title,
                snippet=parsed.snippet,
                author=None,
                published_ts=parsed.published_ts,
                collected_ts=collected_at,
                external_id=external_id,
                raw_payload={"url": article_url, "title": parsed.title, "source_url": listing_url},
            )
        )

    if not items:
        if skipped_missing_dates:
            raise ValueError(
                "Construction News parser found article links but could not extract trustworthy published dates"
            )
        raise ValueError("Construction News parser did not extract any usable article items")

    return items
