from datetime import datetime, timezone
from pathlib import Path

import pytest

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.parsers.humanoid_robotics_technology import (
    parse_humanoid_robotics_article,
    parse_humanoid_robotics_listing,
)


def _hrt_source() -> SourceDefinition:
    return SourceDefinition(
        id="humanoid_robotics_technology_listing",
        name="Humanoid Robotics Technology",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="humanoid_robotics_technology",
        url="https://humanoidroboticstechnology.com/industry-news/",
        priority=88,
        tags=("robotics", "humanoid", "industrial"),
        extra_config={"article_limit": 20},
    )


def test_parse_hrt_article_extracts_meta_and_json_ld_dates() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    sereact_html = (fixtures / "hrt_sereact_article.html").read_text(encoding="utf-8")
    hexagon_html = (fixtures / "hrt_hexagon_article.html").read_text(encoding="utf-8")

    sereact = parse_humanoid_robotics_article(sereact_html)
    hexagon = parse_humanoid_robotics_article(hexagon_html)

    assert sereact.title == "Sereact announces EUR 110M Series B round"
    assert sereact.published_ts == datetime(2026, 4, 27, 9, 15, tzinfo=timezone.utc)
    assert "AI robotics stack" in (sereact.snippet or "")

    assert hexagon.title == "Hexagon Robotics and Schaeffler announce deployment of AEON humanoids"
    assert hexagon.published_ts == datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc)


def test_parse_hrt_listing_collects_article_pages() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    listing_html = (fixtures / "hrt_listing.html").read_text(encoding="utf-8")
    page_map = {
        "https://humanoidroboticstechnology.com/industry-news/sereact-announces-110m-series-b-round/": (
            fixtures / "hrt_sereact_article.html"
        ).read_text(encoding="utf-8"),
        "https://humanoidroboticstechnology.com/industry-news/generative-bionics-and-italdesign-enter-a-strategic-partnership/": (
            fixtures / "hrt_generative_bionics_article.html"
        ).read_text(encoding="utf-8"),
        "https://humanoidroboticstechnology.com/industry-news/hexagon-robotics-and-schaeffler-announce-deployment-of-aeon-humanoids/": (
            fixtures / "hrt_hexagon_article.html"
        ).read_text(encoding="utf-8"),
    }

    def fake_fetch(url: str) -> str:
        return page_map[url]

    items = parse_humanoid_robotics_listing(
        listing_html=listing_html,
        source=_hrt_source(),
        collected_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
        fetch_text_fn=fake_fetch,
    )

    assert len(items) == 3
    assert items[0].url.startswith("https://humanoidroboticstechnology.com/industry-news/")
    assert all(item.published_ts is not None for item in items)
    assert any("Sereact" in item.title for item in items)


def test_parse_hrt_listing_collects_from_live_like_absolute_links_and_skips_pagination() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    listing_html = (fixtures / "hrt_listing_live_like.html").read_text(encoding="utf-8")
    page_map = {
        "https://humanoidroboticstechnology.com/industry-news/sereact-announces-110m-series-b-round/": (
            fixtures / "hrt_sereact_article.html"
        ).read_text(encoding="utf-8"),
        "https://humanoidroboticstechnology.com/industry-news/generative-bionics-and-italdesign-enter-a-strategic-partnership/": (
            fixtures / "hrt_generative_bionics_article.html"
        ).read_text(encoding="utf-8"),
    }

    source = SourceDefinition(
        **{
            **_hrt_source().__dict__,
            "url": "https://humanoidroboticstechnology.com/category/industry-news/",
            "extra_config": {"article_limit": 2},
        }
    )

    def fake_fetch(url: str) -> str:
        return page_map[url]

    items = parse_humanoid_robotics_listing(
        listing_html=listing_html,
        source=source,
        collected_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
        fetch_text_fn=fake_fetch,
    )

    assert len(items) == 2
    assert all("/industry-news/" in item.url for item in items)
    assert all("/page/" not in item.url for item in items)


def test_parse_hrt_listing_fails_without_trustworthy_article_dates() -> None:
    listing_html = """
    <html><body><a href="/industry-news/example-story/">Example story</a></body></html>
    """
    article_html = "<html><body><h1>Example story</h1><p>No published date here.</p></body></html>"

    def fake_fetch(url: str) -> str:
        return article_html

    with pytest.raises(ValueError, match="trustworthy published dates"):
        parse_humanoid_robotics_listing(
            listing_html=listing_html,
            source=_hrt_source(),
            collected_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
            fetch_text_fn=fake_fetch,
        )
