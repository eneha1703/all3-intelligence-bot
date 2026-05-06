import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.pipeline.radar_service import RadarService
from all3_radar.sources.registry import SourceRegistry


def test_construction_news_listing_collects_into_normal_pipeline(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_construction_news.db"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))

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
        "https://www.constructionnews.co.uk/cn-intelligence/": listing_html,
        "https://www.constructionnews.co.uk/cn-intelligence/sector/": sector_html,
        "https://www.constructionnews.co.uk/cn-intelligence/uk-construction-activity-march-2026-infrastructure-05-05-2026/": article_one,
        "https://www.constructionnews.co.uk/cn-intelligence/materials-prices-rise-as-labour-costs-bite-06-05-2026/": article_two,
    }

    registry = SourceRegistry(
        (
            SourceDefinition(
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
                    "listing_urls": ("https://www.constructionnews.co.uk/cn-intelligence/sector/",),
                    "market_scope": "uk_construction_market",
                },
            ),
        )
    )

    def fake_fetch_text(url: str) -> str:
        return page_map[url]

    caplog.set_level("INFO")
    service = RadarService(repo_root=repo_root, registry=registry, fetch_text_fn=fake_fetch_text)
    result = service.run(dry_run=True)

    assert result.selected_sources == 1
    assert result.collected_items == 2
    assert result.normalized_items == 2
    assert result.missing_published_ts == 0
    assert result.failed_sources == 0

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT ni.source_id, ni.title, rd.relevance_status, rd.send_status, rd.skip_reason, rd.signals_json
            FROM normalized_items ni
            JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
            ORDER BY ni.title
            """
        ).fetchall()

    assert all(row[0] == "construction_news_intelligence_listing" for row in rows)
    assert any("UK construction activity falls" in row[1] for row in rows)
    fresh_row = next(row for row in rows if row[2] == "keep")
    editorial_flags = json.loads(fresh_row[5])["editorial_flags"]
    assert editorial_flags["uk_construction_market_alert_signal"] is True
    assert editorial_flags["telegram_worthy"] is True
    assert "Collected items from source: id=construction_news_intelligence_listing count=2" in caplog.text
    assert "Source processing summary: id=construction_news_intelligence_listing collected=2 normalized=2" in caplog.text
