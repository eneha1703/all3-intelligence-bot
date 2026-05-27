from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.listing import ListingSourceAdapter


def _german_press_date(value: datetime) -> str:
    months = {
        1: "Januar",
        2: "Februar",
        3: "MГ¤rz",
        4: "April",
        5: "Mai",
        6: "Juni",
        7: "Juli",
        8: "August",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "Dezember",
    }
    return f"{value.day}. {months[value.month]} {value.year}"


def test_listing_adapter_retries_transient_listing_fetch(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    now = datetime(2026, 5, 12, tzinfo=timezone.utc)
    html = (
        (repo_root / "tests" / "fixtures" / "destatis_press_listing.html")
        .read_text(encoding="utf-8")
        .replace("__FRESH_DATE_GERMAN__", _german_press_date(now))
        .replace("__STALE_DATE_GERMAN__", _german_press_date(now))
    )
    source = SourceDefinition(
        id="destatis_press_listing",
        name="Destatis Press",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="destatis_press",
        url="https://www.destatis.de/EN/Press/_node.html",
        priority=75,
        tags=("policy", "statistics"),
    )
    attempts = 0

    def fake_fetch(url: str) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(url, 503, "Service Temporarily Unavailable", hdrs=None, fp=None)
        return html

    monkeypatch.setattr("all3_radar.sources.listing.time.sleep", lambda _seconds: None)

    adapter = ListingSourceAdapter(fetch_text_fn=fake_fetch)
    items = adapter.collect(source, now)

    assert attempts == 2
    assert len(items) == 2


def test_listing_adapter_falls_back_to_secondary_haufe_listing_when_primary_fails(monkeypatch) -> None:
    source = SourceDefinition(
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
            "listing_urls": ("https://www.haufe.de/immobilien/entwicklung-vermarktung/marktanalysen/",),
            "article_limit": 10,
        },
    )
    secondary_listing = """
    <html><body>
      <a href="/immobilien/entwicklung-vermarktung/marktanalysen/good-story_84324_222222.html">Good</a>
    </body></html>
    """
    article_url = "https://www.haufe.de/immobilien/entwicklung-vermarktung/marktanalysen/good-story_84324_222222.html"
    article_html = """
    <html><head>
      <meta property="og:title" content="Wohnungsbedarf bleibt hoch" />
      <meta property="article:published_time" content="2026-05-06T09:00:00+00:00" />
      <meta name="description" content="Neue Analyse zeigt weiter hohen Wohnungsbedarf." />
    </head></html>
    """

    def fake_fetch(url: str) -> str:
        if url == "https://www.haufe.de/immobilien/":
            raise HTTPError(url, 503, "Service Temporarily Unavailable", hdrs=None, fp=None)
        if url == "https://www.haufe.de/immobilien/entwicklung-vermarktung/marktanalysen/":
            return secondary_listing
        if url == article_url:
            return article_html
        raise AssertionError(f"Unexpected fetch URL: {url}")

    monkeypatch.setattr("all3_radar.sources.listing.time.sleep", lambda _seconds: None)

    adapter = ListingSourceAdapter(fetch_text_fn=fake_fetch)
    items = adapter.collect(source, datetime(2026, 5, 6, tzinfo=timezone.utc))

    assert len(items) == 1
    assert items[0].url == article_url


def test_listing_adapter_falls_back_to_secondary_construction_news_listing() -> None:
    source = SourceDefinition(
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
        extra_config={
            "article_limit": 20,
            "listing_urls": (
                "https://www.constructionnews.co.uk/cn-intelligence/sector/",
                "https://www.constructionnews.co.uk/sections/data/",
                "https://www.constructionnews.co.uk/contracts/",
            ),
        },
    )
    article_html = """
    <html>
      <head>
        <meta property="og:title" content="£1.25bn housing and demolition framework launched" />
        <meta name="description" content="A new UK framework covers housing, demolition and public-sector procurement." />
        <meta property="article:published_time" content="2026-05-11T08:00:00Z" />
      </head>
      <body></body>
    </html>
    """
    contracts_html = """
    <html><body>
      <a href="/contracts/1-25bn-housing-and-demolition-framework-launched-11-05-2026/">Story one</a>
    </body></html>
    """

    def fake_fetch(url: str) -> str:
        if url == "https://www.constructionnews.co.uk/cn-intelligence/":
            raise RuntimeError("403")
        if url == "https://www.constructionnews.co.uk/cn-intelligence/sector/":
            raise RuntimeError("403")
        if url == "https://www.constructionnews.co.uk/sections/data/":
            raise RuntimeError("403")
        if url == "https://www.constructionnews.co.uk/contracts/":
            return contracts_html
        return article_html

    adapter = ListingSourceAdapter(fetch_text_fn=fake_fetch)
    items = adapter.collect(source, datetime(2026, 5, 12, tzinfo=timezone.utc))

    assert len(items) == 1
    assert items[0].url == "https://www.constructionnews.co.uk/contracts/1-25bn-housing-and-demolition-framework-launched-11-05-2026/"
