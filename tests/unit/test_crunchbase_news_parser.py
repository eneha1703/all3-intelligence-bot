from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.parsers.crunchbase_news import (
    parse_crunchbase_news_article,
    parse_crunchbase_news_listing,
)


def _source() -> SourceDefinition:
    return SourceDefinition(
        id="crunchbase_news_listing",
        name="Crunchbase News",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="crunchbase_news",
        url="https://news.crunchbase.com/sections/real-estate-property-tech/",
        priority=68,
        tags=("construction", "robotics", "funding"),
        extra_config={
            "article_limit": 12,
            "listing_urls": ("https://news.crunchbase.com/robotics/",),
        },
    )


def test_parse_crunchbase_article_extracts_meta() -> None:
    article_html = """
    <html>
      <head>
        <meta property="og:title" content="Exclusive: AI-Powered Construction Procurement Startup Lands $20M Series A" />
        <meta name="description" content="Parspec has raised a $20 million Series A to improve efficiency in the construction supply chain." />
        <meta property="article:published_time" content="2025-07-08T12:00:00Z" />
      </head>
      <body><h1>Ignored fallback</h1></body>
    </html>
    """

    parsed = parse_crunchbase_news_article(article_html)

    assert parsed.title == "Exclusive: AI-Powered Construction Procurement Startup Lands $20M Series A"
    assert parsed.published_ts == datetime(2025, 7, 8, 12, 0, tzinfo=timezone.utc)
    assert "construction supply chain" in (parsed.snippet or "")


def test_parse_crunchbase_listing_collects_article_pages_from_archive_sections() -> None:
    listing_html = """
    <html><body>
      <h2><a href="/real-estate-property-tech/xpanner-automation-as-a-service-for-construction-sites-startup-funding-physical-ai-robotics/">XPanner story</a></h2>
      <h2><a href="/real-estate-property-tech/rebar-lands-14m-ai-hvac/">Rebar story</a></h2>
      <a href="/sections/real-estate-property-tech/">Archive home</a>
    </body></html>
    """
    robotics_html = """
    <html><body>
      <h2><a href="/robotics/physical-ai-custom-robot-builder-seed-funding-anvil/">Anvil story</a></h2>
    </body></html>
    """
    article_map = {
        "https://news.crunchbase.com/real-estate-property-tech/xpanner-automation-as-a-service-for-construction-sites-startup-funding-physical-ai-robotics/": """
        <html><head>
          <meta property="og:title" content="XPanner Raises Funding For Construction-Site Automation" />
          <meta name="description" content="XPanner is building automation-as-a-service for construction sites." />
          <meta property="article:published_time" content="2026-05-14T08:00:00Z" />
        </head></html>
        """,
        "https://news.crunchbase.com/real-estate-property-tech/rebar-lands-14m-ai-hvac/": """
        <html><head>
          <meta property="og:title" content="Rebar Lands $14M To Help HVAC Suppliers Generate Quotes Faster With AI" />
          <meta name="description" content="Rebar is focused on commercial HVAC supplier workflows." />
          <meta property="article:published_time" content="2026-03-10T10:00:00Z" />
        </head></html>
        """,
        "https://news.crunchbase.com/robotics/physical-ai-custom-robot-builder-seed-funding-anvil/": """
        <html><head>
          <meta property="og:title" content="Anvil Robotics Raises $5.5M" />
          <meta name="description" content="Anvil is building a physical AI platform." />
          <meta property="article:published_time" content="2026-04-02T09:00:00Z" />
        </head></html>
        """,
    }

    def fake_fetch(url: str) -> str:
        if url == "https://news.crunchbase.com/robotics/":
            return robotics_html
        return article_map[url]

    items = parse_crunchbase_news_listing(
        listing_html=listing_html,
        source=_source(),
        collected_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        fetch_text_fn=fake_fetch,
    )

    assert len(items) == 3
    assert items[0].source_id == "crunchbase_news_listing"
    assert any("XPanner" in item.title for item in items)
    assert any("/robotics/" in item.url for item in items)
