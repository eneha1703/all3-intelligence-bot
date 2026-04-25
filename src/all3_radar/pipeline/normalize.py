"""Normalization logic for collected items."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from all3_radar.domain.models import CollectedRawItem, NormalizedItem, SourceDefinition

TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "fbclid", "gclid")
WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = WHITESPACE_RE.sub(" ", value).strip()
    return normalized or None


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    return urlunparse(parsed._replace(query=urlencode(filtered_query), fragment=""))


def normalize_collected_item(source: SourceDefinition, item: CollectedRawItem) -> NormalizedItem | None:
    title = _clean_text(item.title)
    if not title:
        return None

    canonical_url = normalize_url(item.url.strip())
    domain = urlparse(canonical_url).netloc.lower()
    if not canonical_url or not domain:
        return None

    return NormalizedItem(
        source_id=source.id,
        canonical_url=canonical_url,
        domain=domain,
        title=title,
        dek=None,
        text_preview=_clean_text(item.snippet),
        published_ts=item.published_ts,
        collected_ts=item.collected_ts,
        language=None,
        layer=source.layer,
        is_wrapper=source.is_wrapper,
        directness_rank=100 if source.is_direct_source else 10,
        metadata={
            "external_id": item.external_id,
            "parser": source.parser,
            "tags": list(source.tags),
        },
    )
