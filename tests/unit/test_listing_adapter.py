from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.listing import ListingSourceAdapter


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
