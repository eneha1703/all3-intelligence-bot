import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.pipeline.radar_service import RadarService
from all3_radar.sources.registry import SourceRegistry


def test_radar_collection_persists_direct_source_items(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar.db"
    feed_path = repo_root / "tests" / "fixtures" / "sample_direct_feed.xml"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    registry = SourceRegistry(
        (
            SourceDefinition(
                id="sample_direct_rss",
                name="Sample Direct RSS",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/feed.xml",
                priority=100,
                tags=("robotics", "construction"),
            ),
        )
    )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/feed.xml"
        template = feed_path.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc)
        return (
            template.replace("__FRESH_DATE__", format_datetime(now - timedelta(hours=3)))
            .replace("__STALE_DATE__", format_datetime(now - timedelta(days=14)))
        )

    caplog.set_level("INFO")
    service = RadarService(repo_root=repo_root, registry=registry, fetch_text_fn=fake_fetch_text)
    result = service.run(dry_run=True)

    assert result.selected_sources == 1
    assert result.collected_items == 3
    assert result.normalized_items == 3
    assert result.fresh_items == 1
    assert result.stale_items == 1
    assert result.missing_published_ts == 1

    with sqlite3.connect(db_path) as connection:
        raw_count = connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
        normalized_count = connection.execute("SELECT COUNT(*) FROM normalized_items").fetchone()[0]
        freshness_rows = connection.execute(
            "SELECT freshness_status, send_status FROM radar_decisions ORDER BY freshness_status"
        ).fetchall()
        normalized_url = connection.execute(
            "SELECT canonical_url FROM normalized_items WHERE title = ?",
            ("Recent robotics deployment wins major contract",),
        ).fetchone()[0]

    assert raw_count == 3
    assert normalized_count == 3
    assert freshness_rows == [
        ("fresh", "stored_only"),
        ("missing_published_ts", "skip"),
        ("stale", "skip"),
    ]
    assert normalized_url == "https://example.com/recent-story"
    assert "Loaded source inventory" in caplog.text
    assert "Collected items from source: id=sample_direct_rss count=3" in caplog.text
