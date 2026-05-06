"""Listing-page source adapter implementations."""

from __future__ import annotations

from datetime import datetime

from all3_radar.domain.models import CollectedRawItem, SourceDefinition
from all3_radar.sources.base import FetchText, UnsupportedSourceError
from all3_radar.sources.parsers.construction_news_intelligence import parse_construction_news_listing
from all3_radar.sources.parsers.destatis_press import parse_destatis_press_listing
from all3_radar.sources.parsers.haufe_immobilien import parse_haufe_immobilien_listing
from all3_radar.sources.parsers.humanoid_robotics_technology import parse_humanoid_robotics_listing
from all3_radar.sources.rss import fetch_text


class ListingSourceAdapter:
    def __init__(self, fetch_text_fn: FetchText | None = None) -> None:
        self._fetch_text = fetch_text_fn or fetch_text

    def collect(self, source: SourceDefinition, collected_at: datetime) -> list[CollectedRawItem]:
        listing_text = self._fetch_text(source.url)
        if source.parser == "destatis_press":
            return parse_destatis_press_listing(feed_text=listing_text, source=source, collected_at=collected_at)
        if source.parser == "humanoid_robotics_technology":
            return parse_humanoid_robotics_listing(
                listing_html=listing_text,
                source=source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        if source.parser == "construction_news_intelligence":
            return parse_construction_news_listing(
                listing_html=listing_text,
                source=source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        if source.parser == "haufe_immobilien":
            return parse_haufe_immobilien_listing(
                listing_html=listing_text,
                source=source,
                collected_at=collected_at,
                fetch_text_fn=self._fetch_text,
            )
        raise UnsupportedSourceError(f"Listing source parser not implemented yet: {source.parser}")
