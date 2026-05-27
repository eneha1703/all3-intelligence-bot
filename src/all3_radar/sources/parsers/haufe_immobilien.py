"""Parser for Haufe Immobilien listing and article pages."""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText
from all3_radar.sources.rss import _clean_text, parse_published_timestamp

LOGGER = logging.getLogger(__name__)

ARTICLE_PATH_RE = re.compile(r"^/immobilien/[^?#]+_\d+_\d+\.html$")
META_TAG_RE = re.compile(
    r'<meta\s+[^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TIME_TAG_RE = re.compile(r'<time[^>]*(?:datetime|content)=["\']([^"\']+)["\']', re.IGNORECASE)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
GERMAN_DATE_RE = re.compile(
    r"\b(\d{1,2})\.\s*"
    r"(Januar|Februar|M(?:aerz|är|Ã¤r)z|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)
MONTHS = {
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "märz": 3,
    "mã¤rz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}
BOILERPLATE_TERMS = (
    "newsletter",
    "haufe.de",
    "login",
    "registrieren",
    "werben",
    "datenschutz",
)
MAX_SNIPPET_CHARS = 900
MAX_SNIPPET_PARAGRAPHS = 3


class _HaufeListingParser(HTMLParser):
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
        if ARTICLE_PATH_RE.match(urlparse(absolute).path) and absolute not in self.article_urls:
            self.article_urls.append(absolute)


@dataclass(frozen=True)
class ParsedHaufeArticle:
    title: str
    published_ts: datetime | None
    snippet: str | None


def _extract_meta_map(article_html: str) -> dict[str, str]:
    return {name.lower(): html.unescape(content).strip() for name, content in META_TAG_RE.findall(article_html)}


def _extract_json_ld_published(article_html: str) -> datetime | None:
    for raw_block in JSON_LD_RE.findall(article_html):
        try:
            payload = json.loads(raw_block.strip())
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            date_value = candidate.get("datePublished") or candidate.get("dateCreated") or candidate.get("dateModified")
            if isinstance(date_value, str):
                parsed = parse_haufe_published_ts(date_value)
                if parsed is not None:
                    return parsed
    return None


def parse_haufe_published_ts(value: str) -> datetime | None:
    candidate = _clean_text(value)
    if not candidate:
        return None

    parsed = parse_published_timestamp(candidate)
    if parsed is not None:
        return parsed

    numeric_match = NUMERIC_DATE_RE.search(candidate)
    if numeric_match:
        day = int(numeric_match.group(1))
        month = int(numeric_match.group(2))
        year = int(numeric_match.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)

    german_match = GERMAN_DATE_RE.search(candidate)
    if german_match:
        day = int(german_match.group(1))
        month_name = german_match.group(2).lower()
        year = int(german_match.group(3))
        month = MONTHS.get(month_name)
        if month is not None:
            return datetime(year, month, day, tzinfo=timezone.utc)

    return None


def _extract_meaningful_paragraphs(article_html: str) -> list[str]:
    paragraphs: list[str] = []
    for match in PARAGRAPH_RE.findall(article_html):
        text = _clean_text(re.sub(r"<[^>]+>", " ", match))
        if not text:
            continue
        lowered = text.lower()
        if any(term in lowered for term in BOILERPLATE_TERMS):
            continue
        if text in paragraphs:
            continue
        paragraphs.append(text)
    return paragraphs


def _build_article_excerpt(description: str | None, article_html: str) -> str | None:
    parts: list[str] = []
    if description:
        parts.append(description)

    for paragraph in _extract_meaningful_paragraphs(article_html):
        if any(paragraph in existing or existing in paragraph for existing in parts):
            continue
        candidate_parts = [*parts, paragraph]
        candidate = " ".join(candidate_parts).strip()
        if len(candidate) > MAX_SNIPPET_CHARS and parts:
            break
        parts.append(paragraph)
        if len(parts) >= MAX_SNIPPET_PARAGRAPHS:
            break

    if not parts:
        return None

    snippet = " ".join(parts).strip()
    if len(snippet) <= MAX_SNIPPET_CHARS:
        return snippet
    truncated = snippet[: MAX_SNIPPET_CHARS + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return truncated or snippet[:MAX_SNIPPET_CHARS].rstrip(" ,;:-")


def _extract_article_urls(listing_html: str, base_url: str) -> list[str]:
    parser = _HaufeListingParser(base_url=base_url)
    parser.feed(listing_html)
    parser.close()
    return parser.article_urls


def parse_haufe_article(article_html: str) -> ParsedHaufeArticle:
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
        raise ValueError("Haufe parser could not extract a title")

    published_ts = None
    for key in ("article:published_time", "og:published_time", "date", "publish-date", "dc.date"):
        candidate = meta.get(key)
        if candidate:
            published_ts = parse_haufe_published_ts(candidate)
            if published_ts is not None:
                break
    if published_ts is None:
        time_match = TIME_TAG_RE.search(article_html)
        if time_match:
            published_ts = parse_haufe_published_ts(time_match.group(1))
    if published_ts is None:
        published_ts = _extract_json_ld_published(article_html)
    if published_ts is None:
        published_ts = parse_haufe_published_ts(article_html)

    description = _clean_text(meta.get("description")) or _clean_text(meta.get("og:description"))
    snippet = _build_article_excerpt(description, article_html)
    return ParsedHaufeArticle(title=title, published_ts=published_ts, snippet=snippet)


def parse_haufe_immobilien_listing(
    listing_html: str,
    source: SourceDefinition,
    collected_at: datetime,
    fetch_text_fn: FetchText,
) -> list[CollectedRawItem]:
    listing_urls = [source.url, *tuple(str(url) for url in source.extra_config.get("listing_urls", ()))]
    article_urls: list[str] = []
    for listing_url in listing_urls:
        try:
            current_html = listing_html if listing_url == source.url else fetch_text_fn(listing_url)
        except Exception as exc:
            LOGGER.warning(
                "Haufe listing page fetch failed; skipping page: source=%s url=%s reason=%s",
                source.id,
                listing_url,
                exc,
            )
            continue
        for article_url in _extract_article_urls(current_html, listing_url):
            if article_url not in article_urls:
                article_urls.append(article_url)

    article_limit = int(source.extra_config.get("article_limit", 20))
    items: list[CollectedRawItem] = []
    skipped_missing_dates = 0
    skipped_fetch_failures = 0
    for article_url in article_urls[:article_limit]:
        try:
            article_html = fetch_text_fn(article_url)
        except Exception as exc:
            skipped_fetch_failures += 1
            LOGGER.warning(
                "Haufe article fetch failed; skipping article: source=%s url=%s reason=%s",
                source.id,
                article_url,
                exc,
            )
            continue
        parsed = parse_haufe_article(article_html)
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
        if skipped_fetch_failures:
            raise ValueError("Haufe parser found article links but all usable article fetches failed")
        if skipped_missing_dates:
            raise ValueError("Haufe parser found article links but could not extract trustworthy published dates")
        raise ValueError("Haufe parser did not extract any usable article items")

    return items
