from datetime import datetime, timezone

import pytest

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.parsers.construction_news_intelligence import (
    parse_construction_news_article,
    parse_construction_news_listing,
)


def _construction_news_source() -> SourceDefinition:
    return SourceDefinition(
        id="construction_news_intelligence_listing",
        name="Construction News Intelligence",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="construction_news_intelligence",
        url="https://www.constructionnews.co.uk/cn-intelligence/",
        priority=72,
        tags=("construction", "uk", "market"),
        extra_config={"article_limit": 20, "listing_urls": ("https://www.constructionnews.co.uk/cn-intelligence/sector/",)},
    )


def test_parse_construction_news_article_extracts_title_date_and_snippet() -> None:
    article_html = """
    <html>
      <head>
        <meta property="og:title" content="UK construction activity falls as infrastructure starts weaken" />
        <meta name="description" content="A new report says construction activity, project starts and main contract awards fell across infrastructure and commercial work." />
        <meta property="article:published_time" content="2026-05-05T08:30:00Z" />
      </head>
      <body>
        <h1>UK construction activity falls as infrastructure starts weaken</h1>
      </body>
    </html>
    """

    parsed = parse_construction_news_article(article_html)

    assert parsed.title == "UK construction activity falls as infrastructure starts weaken"
    assert parsed.published_ts == datetime(2026, 5, 5, 8, 30, tzinfo=timezone.utc)
    assert "main contract awards fell" in (parsed.snippet or "")


def test_parse_construction_news_listing_collects_listing_and_sector_pages() -> None:
    listing_html = """
    <html><body>
      <a href="/cn-intelligence/uk-construction-activity-march-2026-infrastructure-05-05-2026/">Story one</a>
    </body></html>
    """
    sector_html = """
    <html><body>
      <a href="/cn-intelligence/materials-prices-rise-as-labour-costs-bite-06-05-2026/">Story two</a>
    </body></html>
    """
    article_one = """
    <html>
      <head>
        <meta property="og:title" content="UK construction activity falls as infrastructure starts weaken" />
        <meta name="description" content="A new report says construction activity, project starts and main contract awards fell across infrastructure and commercial work." />
        <meta property="article:published_time" content="2026-05-05T08:30:00Z" />
      </head>
      <body></body>
    </html>
    """
    article_two = """
    <html>
      <head>
        <meta property="og:title" content="Materials prices rise as labour costs bite across UK construction" />
        <script type="application/ld+json">
          {"@type":"NewsArticle","datePublished":"2026-05-06T07:00:00Z"}
        </script>
      </head>
      <body>
        <p>Materials prices and labour costs rose across regional construction markets in the latest report.</p>
      </body>
    </html>
    """
    page_map = {
        "https://www.constructionnews.co.uk/cn-intelligence/sector/": sector_html,
        "https://www.constructionnews.co.uk/cn-intelligence/uk-construction-activity-march-2026-infrastructure-05-05-2026/": article_one,
        "https://www.constructionnews.co.uk/cn-intelligence/materials-prices-rise-as-labour-costs-bite-06-05-2026/": article_two,
    }

    def fake_fetch(url: str) -> str:
        return page_map[url]

    items = parse_construction_news_listing(
        listing_html=listing_html,
        source=_construction_news_source(),
        collected_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
        fetch_text_fn=fake_fetch,
    )

    assert len(items) == 2
    assert items[0].url.startswith("https://www.constructionnews.co.uk/cn-intelligence/")
    assert all(item.published_ts is not None for item in items)
    assert any("Materials prices rise" in item.title for item in items)


def test_parse_construction_news_listing_fails_without_trustworthy_dates() -> None:
    listing_html = """
    <html><body>
      <a href="/cn-intelligence/example-story/">Example story</a>
    </body></html>
    """
    article_html = """
    <html>
      <body>
        <h1>Example story</h1>
        <p>This report covers construction activity in the UK market.</p>
      </body>
    </html>
    """

    def fake_fetch(url: str) -> str:
        return article_html

    with pytest.raises(ValueError, match="trustworthy published dates"):
        parse_construction_news_listing(
            listing_html=listing_html,
            source=_construction_news_source(),
            collected_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
            fetch_text_fn=fake_fetch,
        )
