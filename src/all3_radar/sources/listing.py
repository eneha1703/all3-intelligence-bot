"""Listing-page source adapter implementations."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText, UnsupportedSourceError
from all3_radar.sources.parsers.construction_news_intelligence import parse_construction_news_listing
from all3_radar.sources.parsers.crunchbase_news import parse_crunchbase_news_listing
from all3_radar.sources.parsers.destatis_press import parse_destatis_press_listing
from all3_radar.sources.parsers.haufe_immobilien import parse_haufe_immobilien_listing
from all3_radar.sources.parsers.humanoid_robotics_technology import parse_humanoid_robotics_listing
from all3_radar.sources.rss import fetch_text

LOGGER = logging.getLogger(__name__)


class ListingSourceAdapter:
    def __init__(self, fetch_text_fn: FetchText | None = None) -> None:
        self._fetch_text = fetch_text_fn or fetch_text

    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        effective_source = source
        listing_text: str | None = None

        if source.parser == "construction_news_intelligence":
            candidate_urls = [source.url, *tuple(str(url) for url in source.extra_config.get("listing_urls", ()))]
            last_error: Exception | None = None
            for candidate_url in candidate_urls:
                try:
                    listing_text = self._fetch_text(candidate_url)
                    if candidate_url != source.url:
                        remaining_urls = tuple(url for url in candidate_urls if url != candidate_url)
                        effective_source = replace(
                            source,
                            url=candidate_url,
                            extra_config={**source.extra_config, "listing_urls": remaining_urls},
                        )
                    break
                except Exception as exc:
                    last_error = exc
                    LOGGER.warning(
                        "Listing fetch failed: source=%s url=%s reason=%s",
                        source.id,
                        candidate_url,
                        exc,
                    )
            if listing_text is None and last_error is not None:
                raise last_error
        else:
            listing_text = self._fetch_text(source.url)

        if source.parser == "destatis_press":
            return parse_destatis_press_listing(feed_text=listing_text, source=source, collected_at=collected_at)
        if source.parser == "humanoid_robotics_technology":
            return parse_humanoid_robotics_listing(
                listing_html=listing_text,
                source=effective_source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        if source.parser == "construction_news_intelligence":
            return parse_construction_news_listing(
                listing_html=listing_text,
                source=effective_source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        if source.parser == "haufe_immobilien":
            return parse_haufe_immobilien_listing(
                listing_html=listing_text,
                source=effective_source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        if source.parser == "crunchbase_news":
            return parse_crunchbase_news_listing(
                listing_html=listing_text,
                source=effective_source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        raise UnsupportedSourceError(f"Listing source parser not implemented yet: {source.parser}")
