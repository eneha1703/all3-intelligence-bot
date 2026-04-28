import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.pipeline.radar_service import RadarService
from all3_radar.sources.registry import SourceRegistry


def _german_press_date(value: datetime) -> str:
    months = {
        1: "Januar",
        2: "Februar",
        3: "März",
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


def test_destatis_listing_collects_into_normal_pipeline(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_destatis.db"
    fixture_path = repo_root / "tests" / "fixtures" / "destatis_press_listing.html"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    now = datetime.now(timezone.utc)
    html = (
        fixture_path.read_text(encoding="utf-8")
        .replace("__FRESH_DATE_GERMAN__", _german_press_date(now - timedelta(hours=6)))
        .replace("__STALE_DATE_GERMAN__", _german_press_date(now - timedelta(days=60)))
    )

    registry = SourceRegistry(
        (
            SourceDefinition(
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
            ),
        )
    )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://www.destatis.de/EN/Press/_node.html"
        return html

    caplog.set_level("INFO")
    service = RadarService(repo_root=repo_root, registry=registry, fetch_text_fn=fake_fetch_text)
    result = service.run(dry_run=True)

    assert result.selected_sources == 1
    assert result.collected_items == 2
    assert result.normalized_items == 2
    assert result.fresh_items == 1
    assert result.stale_items == 1
    assert result.missing_published_ts == 0
    assert result.failed_sources == 0

    with sqlite3.connect(db_path) as connection:
        raw_count = connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
        normalized_rows = connection.execute(
            """
            SELECT ni.source_id, ni.canonical_url, ni.title, ni.published_ts, rd.freshness_status, rd.send_status, rd.skip_reason, rd.signals_json
            FROM normalized_items ni
            JOIN radar_decisions rd ON rd.normalized_item_id = ni.id
            ORDER BY ni.title
            """
        ).fetchall()

    assert raw_count == 2
    assert normalized_rows[0][0] == "destatis_press_listing"
    assert normalized_rows[0][1].startswith("https://www.destatis.de/DE/Presse/Pressemitteilungen/")
    assert normalized_rows[0][3] is not None
    assert any(row[4:7] == ("fresh", "stored_only", None) for row in normalized_rows)
    assert any(row[4:7] == ("stale", "skip", "freshness_failed") for row in normalized_rows)
    fresh_row = next(row for row in normalized_rows if row[4] == "fresh")
    editorial_flags = json.loads(fresh_row[7])["editorial_flags"]
    assert editorial_flags["official_construction_market_signal"] is True
    assert editorial_flags["telegram_worthy"] is True
    assert "Collected items from source: id=destatis_press_listing count=2" in caplog.text
    assert "Source processing summary: id=destatis_press_listing collected=2 normalized=2" in caplog.text
