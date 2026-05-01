"""RSS source adapter implementations."""

from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "new_all3_radar_bot/0.1 (+https://github.com/togetherwithyouapi-commits/new_all3_radar_bot)"
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
BARE_AMPERSAND_RE = re.compile(r"&(?!#?[A-Za-z0-9]+;)")


def fetch_text(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(element: ET.Element, *names: str) -> str | None:
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child.tag) in names and child.text:
            text = child.text.strip()
            if text:
                return text
    return None


def _extract_link(entry: ET.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return _first_text(entry, "link")


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    stripped = HTML_TAG_RE.sub(" ", html.unescape(value))
    normalized = WHITESPACE_RE.sub(" ", stripped).strip()
    return normalized or None


def parse_published_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw_value = value.strip()
    if not raw_value:
        return None

    for candidate in (raw_value, raw_value.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    try:
        parsed = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_rss_items(feed_text: str, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError:
        repaired_feed_text = BARE_AMPERSAND_RE.sub("&amp;", feed_text)
        root = ET.fromstring(repaired_feed_text)
    entries = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    items: list[CollectedRawItem] = []

    for entry in entries:
        link = _extract_link(entry)
        title = _clean_text(_first_text(entry, "title"))
        if not link or not title:
            continue

        description = _clean_text(_first_text(entry, "description", "summary", "content"))
        author = _clean_text(_first_text(entry, "author", "creator"))
        published_text = _first_text(entry, "pubDate", "published", "updated", "date")
        guid = _clean_text(_first_text(entry, "guid", "id"))
        published_ts = parse_published_timestamp(published_text)

        items.append(
            CollectedRawItem(
                source_id=source.id,
                url=link,
                title=title,
                snippet=description,
                author=author,
                published_ts=published_ts,
                collected_ts=collected_at,
                external_id=guid,
                raw_payload={
                    "title": title,
                    "link": link,
                    "description": description,
                    "author": author,
                    "published_raw": published_text,
                    "guid": guid,
                    "source_url": source.url,
                    "source_domain": urlparse(source.url).netloc,
                },
            )
        )
    return items


class RssSourceAdapter:
    """Collect direct-source items from RSS or Atom feeds."""

    def __init__(self, fetch_text_fn: FetchText | None = None) -> None:
        self._fetch_text = fetch_text_fn or fetch_text

    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        feed_text = self._fetch_text(source.url)
        return parse_rss_items(feed_text=feed_text, source=source, collected_at=collected_at)
