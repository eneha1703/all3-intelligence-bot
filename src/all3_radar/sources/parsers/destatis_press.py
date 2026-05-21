"""Parser for the Destatis press listing page."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from all3_radar.domain.models import CollectedRawItem, SourceDefinition

WHITESPACE_RE = re.compile(r"\s+")
DESTATIS_ARTICLE_PREFIX = "/DE/Presse/Pressemitteilungen/"
DESTATIS_ARTICLE_PATH_RE = re.compile(r"/DE/Presse/Pressemitteilungen/\d{4}/\d{2}/[^\"'#?]+\.html?$")
GERMAN_DATE_RE = re.compile(
    r"(\d{1,2})\.\s*(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
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
PRESS_META_PREFIX_RE = re.compile(
    r"^Pressemitteilung\s+Nr\.?\s*\S+\s+vom\s+.+?(?=(Der|Die|Im|In|Mit|Für|Fuer)\b)",
    re.IGNORECASE,
)


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = WHITESPACE_RE.sub(" ", html.unescape(value)).strip()
    return normalized or None


def _extract_external_id(url: str) -> str | None:
    path = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return path or None


def _normalize_destatis_article_url(base_url: str, href: str) -> str:
    absolute_url = urljoin(base_url, href)
    parsed = urlparse(absolute_url)
    path = parsed.path

    duplicated_prefix = f"{DESTATIS_ARTICLE_PREFIX}DE/Presse/Pressemitteilungen/"
    if duplicated_prefix in path:
        path = path.replace(duplicated_prefix, DESTATIS_ARTICLE_PREFIX, 1)
        absolute_url = parsed._replace(path=path).geturl()

    return absolute_url


def parse_destatis_published_ts(value: str) -> datetime | None:
    candidate = _clean_text(value)
    if not candidate:
        return None

    german_match = GERMAN_DATE_RE.search(candidate)
    if german_match:
        day = int(german_match.group(1))
        month_name = german_match.group(2).lower()
        year = int(german_match.group(3))
        month = MONTHS.get(month_name)
        if month is not None:
            return datetime(year, month, day, tzinfo=timezone.utc)

    numeric_match = NUMERIC_DATE_RE.search(candidate)
    if numeric_match:
        day = int(numeric_match.group(1))
        month = int(numeric_match.group(2))
        year = int(numeric_match.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)

    return None


def _looks_like_date_container(tag: str, attrs: dict[str, str]) -> bool:
    if tag == "time":
        return True
    for key in ("class", "id", "data-testid"):
        value = attrs.get(key, "")
        if "date" in value.lower():
            return True
    return False


@dataclass
class _PendingEntry:
    url: str
    title_parts: list[str]
    date_parts: list[str]
    context_parts: list[str]


class _DestatisPressHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.pending_entries: list[_PendingEntry] = []
        self.current_entry: _PendingEntry | None = None
        self.current_link: str | None = None
        self._inside_ignored_tag = False
        self._date_container_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._inside_ignored_tag = True
            return

        attr_map = {key: value or "" for key, value in attrs}
        if self.current_entry is not None and _looks_like_date_container(tag, attr_map):
            self._date_container_depth += 1

        if tag != "a":
            return

        href = attr_map.get("href")
        if not href:
            return
        absolute_url = _normalize_destatis_article_url(self.base_url, href)
        if not DESTATIS_ARTICLE_PATH_RE.search(urlparse(absolute_url).path):
            return

        if self.current_entry is not None:
            self.pending_entries.append(self.current_entry)

        self.current_link = absolute_url
        self.current_entry = _PendingEntry(
            url=absolute_url,
            title_parts=[],
            date_parts=[],
            context_parts=[],
        )

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._inside_ignored_tag = False
            return

        if self._date_container_depth and tag in {"time", "span", "div", "p"}:
            self._date_container_depth -= 1

        if tag == "a":
            self.current_link = None

    def handle_data(self, data: str) -> None:
        if self._inside_ignored_tag:
            return

        text = _clean_text(data)
        if not text or self.current_entry is None:
            return

        if self._date_container_depth:
            self.current_entry.date_parts.append(text)
        elif self.current_link is not None:
            self.current_entry.title_parts.append(text)
        else:
            self.current_entry.context_parts.append(text)

    def entries(self) -> list[_PendingEntry]:
        result = list(self.pending_entries)
        if self.current_entry is not None:
            result.append(self.current_entry)
        return result


def parse_destatis_press_listing(feed_text: str, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
    parser = _DestatisPressHTMLParser(base_url=source.url)
    parser.feed(feed_text)
    parser.close()

    items: list[CollectedRawItem] = []
    skipped_missing_date = 0
    for entry in parser.entries():
        title = _clean_text(" ".join(entry.title_parts))
        if not title:
            continue

        date_text = _clean_text(" ".join(entry.date_parts))
        context = _clean_text(" ".join(entry.context_parts))
        published_ts = parse_destatis_published_ts(" ".join(part for part in (date_text, title, context) if part))
        if published_ts is None:
            skipped_missing_date += 1
            continue

        snippet = None
        if context:
            lowered_title = title.lower()
            snippet_source = PRESS_META_PREFIX_RE.sub("", context).strip(" .")
            if lowered_title in snippet_source.lower():
                snippet_source = ""
            snippet = _clean_text(snippet_source)

        items.append(
            CollectedRawItem(
                source_id=source.id,
                url=entry.url,
                title=title,
                snippet=snippet,
                author=None,
                published_ts=published_ts,
                collected_ts=collected_at,
                external_id=_extract_external_id(entry.url),
                raw_payload={
                    "title": title,
                    "url": entry.url,
                    "context_text": context,
                    "date_text": date_text,
                    "source_url": source.url,
                },
            )
        )

    if not items:
        if skipped_missing_date:
            raise ValueError(
                f"Destatis parser found entries but could not extract trustworthy published dates: skipped={skipped_missing_date}"
            )
        raise ValueError("Destatis parser did not extract any listing items")

    return items
