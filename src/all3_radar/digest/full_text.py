"""Best-effort full-text extraction for weekly digest candidates."""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable

from all3_radar.sources.rss import fetch_text

LOGGER = logging.getLogger(__name__)
WHITESPACE_RE = re.compile(r"\s+")
SCRIPT_BLOCK_RE = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ArticleTextResult:
    text: str | None
    status: str


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._current: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag_name = tag.lower()
        if tag_name in {"script", "style", "noscript", "svg", "header", "footer", "nav", "aside"}:
            self._skip_depth += 1
            return
        if tag_name in {"p", "li", "h2", "h3", "blockquote"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if self._skip_depth:
            if tag_name in {"script", "style", "noscript", "svg", "header", "footer", "nav", "aside"}:
                self._skip_depth -= 1
            return
        if tag_name in {"p", "li", "h2", "h3", "blockquote", "div", "section", "article"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        normalized = WHITESPACE_RE.sub(" ", data).strip()
        if normalized:
            self._current.append(normalized)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if not self._current:
            return
        text = WHITESPACE_RE.sub(" ", " ".join(self._current)).strip()
        self._current = []
        if _looks_like_article_block(text):
            self.blocks.append(text)


def _looks_like_article_block(text: str) -> bool:
    if len(text) < 45:
        return False
    normalized = text.lower()
    if any(
        phrase in normalized
        for phrase in (
            "cookie",
            "subscribe",
            "sign up",
            "privacy policy",
            "terms of use",
            "advertisement",
            "all rights reserved",
            "share this article",
            "enable javascript",
        )
    ):
        return False
    return True


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = html.unescape(value)
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned or None


def _extract_json_ld_article_text(article_html: str) -> str | None:
    texts: list[str] = []
    for match in JSON_LD_RE.finditer(article_html):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph")
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
            article_body = candidate.get("articleBody")
            description = candidate.get("description")
            for value in (article_body, description):
                cleaned = _clean_text(str(value)) if value else None
                if cleaned and len(cleaned) > 120:
                    texts.append(cleaned)
    if not texts:
        return None
    return max(texts, key=len)


def extract_article_text(article_html: str, *, max_chars: int = 3500) -> ArticleTextResult:
    json_ld_text = _extract_json_ld_article_text(article_html)
    if json_ld_text:
        return ArticleTextResult(text=_truncate_text(json_ld_text, max_chars), status="json_ld")

    stripped_html = SCRIPT_BLOCK_RE.sub(" ", article_html)
    parser = _ReadableTextParser()
    try:
        parser.feed(stripped_html)
        parser.close()
    except Exception as exc:  # pragma: no cover - HTMLParser is permissive, but keep digest resilient.
        return ArticleTextResult(text=None, status=f"parse_failed:{type(exc).__name__}")

    if not parser.blocks:
        return ArticleTextResult(text=None, status="no_article_text")
    joined = " ".join(parser.blocks)
    return ArticleTextResult(text=_truncate_text(joined, max_chars), status="html_blocks")


def fetch_article_text(
    url: str,
    *,
    timeout_seconds: int = 8,
    max_chars: int = 3500,
    fetch_text_fn: Callable[[str, int], str] | None = None,
) -> ArticleTextResult:
    fetcher = fetch_text_fn or fetch_text
    try:
        article_html = fetcher(url, timeout_seconds)
    except TypeError:
        try:
            article_html = fetcher(url)  # type: ignore[misc]
        except Exception as exc:
            LOGGER.info("Weekly digest full-text fetch failed: url=%s reason=%s", url, exc)
            return ArticleTextResult(text=None, status=f"fetch_failed:{type(exc).__name__}")
    except Exception as exc:
        LOGGER.info("Weekly digest full-text fetch failed: url=%s reason=%s", url, exc)
        return ArticleTextResult(text=None, status=f"fetch_failed:{type(exc).__name__}")
    return extract_article_text(article_html, max_chars=max_chars)


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = WHITESPACE_RE.sub(" ", text).strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    truncated = normalized[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{truncated}..."
