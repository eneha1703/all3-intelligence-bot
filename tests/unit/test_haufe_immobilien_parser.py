from datetime import datetime, timezone

import pytest

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.parsers.haufe_immobilien import parse_haufe_article, parse_haufe_immobilien_listing


def _haufe_source() -> SourceDefinition:
    return SourceDefinition(
        id="haufe_immobilien_listing",
        name="Haufe Immobilien",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="haufe_immobilien",
        url="https://www.haufe.de/immobilien/",
        priority=60,
        tags=("construction", "germany"),
        extra_config={
            "listing_urls": ["https://www.haufe.de/immobilien/investment/"],
            "article_limit": 10,
            "broad_feed": True,
            "market_scope": "germany_housing_market",
        },
    )


def test_parse_haufe_article_extracts_meta_title_and_german_date() -> None:
    article_html = """
    <html>
      <head>
        <meta property="og:title" content="Deutscher Immobilienfinanzierungsindex DIFI steigt" />
        <meta name="description" content="Der DIFI zeigt bessere Erwartungen fuer Immobilienfinanzierungen." />
      </head>
      <body><time datetime="6. Mai 2026"></time></body>
    </html>
    """

    parsed = parse_haufe_article(article_html)

    assert parsed.title == "Deutscher Immobilienfinanzierungsindex DIFI steigt"
    assert parsed.published_ts == datetime(2026, 5, 6, tzinfo=timezone.utc)
    assert "Immobilienfinanzierungen" in (parsed.snippet or "")


def test_parse_haufe_listing_collects_article_pages_from_multiple_listings() -> None:
    home_listing = """
    <html><body>
      <a href="/immobilien/investment/deutscher-immobilienfinanzierungsindex-difi_256_511716.html">DIFI</a>
    </body></html>
    """
    investment_listing = """
    <html><body>
      <a href="https://www.haufe.de/immobilien/entwicklung-vermarktung/marktanalysen/iw-wohnindex-entwicklung-kaufpreise-und-mieten_84324_615168.html">IW Wohnindex</a>
    </body></html>
    """
    article_map = {
        "https://www.haufe.de/immobilien/investment/deutscher-immobilienfinanzierungsindex-difi_256_511716.html": """
            <html><head>
              <meta property="og:title" content="DIFI zeigt bessere Finanzierungslage" />
              <meta property="article:published_time" content="2026-05-06T09:00:00+00:00" />
              <meta name="description" content="Der Finanzierungsindex fuer Immobilien steigt." />
            </head></html>
        """,
        "https://www.haufe.de/immobilien/entwicklung-vermarktung/marktanalysen/iw-wohnindex-entwicklung-kaufpreise-und-mieten_84324_615168.html": """
            <html><head>
              <meta property="og:title" content="IW Wohnindex: Kaufpreise und Mieten steigen" />
              <meta property="article:published_time" content="2026-05-05T09:00:00+00:00" />
              <meta name="description" content="Wohnindex zeigt steigende Kaufpreise und Mieten." />
            </head></html>
        """,
        "https://www.haufe.de/immobilien/investment/": investment_listing,
    }

    def fake_fetch(url: str) -> str:
        return article_map[url]

    items = parse_haufe_immobilien_listing(
        listing_html=home_listing,
        source=_haufe_source(),
        collected_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
        fetch_text_fn=fake_fetch,
    )

    assert len(items) == 2
    assert all(item.source_id == "haufe_immobilien_listing" for item in items)
    assert all(item.published_ts is not None for item in items)
    assert any("DIFI" in item.title for item in items)


def test_parse_haufe_listing_fails_without_trustworthy_dates() -> None:
    listing_html = """
    <html><body>
      <a href="/immobilien/investment/example_256_111111.html">Example</a>
    </body></html>
    """
    article_html = "<html><body><h1>Example</h1><p>No date here.</p></body></html>"

    def fake_fetch(url: str) -> str:
        return article_html

    with pytest.raises(ValueError, match="trustworthy published dates"):
        parse_haufe_immobilien_listing(
            listing_html=listing_html,
            source=_haufe_source(),
            collected_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
            fetch_text_fn=fake_fetch,
        )
