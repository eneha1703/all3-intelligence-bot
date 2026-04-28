import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.pipeline.radar_service import RadarService
from all3_radar.sources.registry import SourceRegistry


def test_hrt_listing_collects_into_normal_pipeline(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_hrt.db"
    fixtures = repo_root / "tests" / "fixtures"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    listing_html = (fixtures / "hrt_listing.html").read_text(encoding="utf-8")
    page_map = {
        "https://humanoidroboticstechnology.com/industry-news/": listing_html,
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

    registry = SourceRegistry(
        (
            SourceDefinition(
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
            ),
        )
    )

    def fake_fetch_text(url: str) -> str:
        return page_map[url]

    caplog.set_level("INFO")
    service = RadarService(repo_root=repo_root, registry=registry, fetch_text_fn=fake_fetch_text)
    result = service.run(dry_run=True)

    assert result.selected_sources == 1
    assert result.collected_items == 3
    assert result.normalized_items == 3
    assert result.fresh_items == 3
    assert result.stale_items == 0
    assert result.missing_published_ts == 0
    assert result.failed_sources == 0

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT ni.source_id, ni.title, ni.canonical_url, rd.relevance_status, rd.send_status, rd.skip_reason, rd.score
            FROM normalized_items ni
            JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
            ORDER BY ni.title
            """
        ).fetchall()

    assert all(row[0] == "humanoid_robotics_technology_listing" for row in rows)
    assert any("Sereact announces" in row[1] for row in rows)
    assert "Collected items from source: id=humanoid_robotics_technology_listing count=3" in caplog.text
    assert "Source processing summary: id=humanoid_robotics_technology_listing collected=3 normalized=3" in caplog.text
