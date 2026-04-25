import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from all3_radar.delivery.telegram import TelegramDelivery
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
    assert result.failed_sources == 0

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


def test_radar_collection_dedupes_and_sends_with_mocks(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_send.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    direct_feed_one = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://direct-a.example/story</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    direct_feed_two = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Construction robot startup Kewazo raises funding for rollout</title>
    <link>https://direct-b.example/story</link>
    <description>The funding will support deployment across industrial construction workflows.</description>
    <pubDate>{format_datetime(now - timedelta(hours=2))}</pubDate>
    <guid>b1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="direct_a",
                name="Direct A",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://direct-a.example/feed.xml",
                priority=90,
                tags=("robotics",),
            ),
            SourceDefinition(
                id="direct_b",
                name="Direct B",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://direct-b.example/feed.xml",
                priority=80,
                tags=("robotics",),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The round supports deployment expansion across construction robotics workflows.", None)

    class FakeTelegramSender:
        def __init__(self) -> None:
            self.sent_cards = []

        def send_card(self, card):
            self.sent_cards.append(card)
            return [
                TelegramDelivery(
                    chat_id="123",
                    status="sent",
                    telegram_message_id="msg-1",
                    error_text=None,
                    payload_text=card.text,
                )
            ]

    feeds = {
        "https://direct-a.example/feed.xml": direct_feed_one,
        "https://direct-b.example/feed.xml": direct_feed_two,
    }

    def fake_fetch_text(url: str) -> str:
        return feeds[url]

    fake_sender = FakeTelegramSender()
    caplog.set_level("INFO")
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        telegram_sender=fake_sender,
    )
    result = service.run(dry_run=False)

    assert result.collected_items == 2
    assert result.canonical_events == 1
    assert result.shortlisted_items == 1
    assert result.sent_items == 1
    assert result.failed_sources == 0
    assert len(fake_sender.sent_cards) == 1
    assert "<b>Kewazo raises funding for construction robot rollout</b>" in fake_sender.sent_cards[0].text

    with sqlite3.connect(db_path) as connection:
        competitor_rows = connection.execute(
            "SELECT competitor_name FROM competitor_matches ORDER BY competitor_name"
        ).fetchall()
        event_member_count = connection.execute("SELECT COUNT(*) FROM event_members").fetchone()[0]
        sent_rows = connection.execute(
            "SELECT status FROM telegram_deliveries WHERE status = 'sent'"
        ).fetchall()

    assert ("Kewazo",) in competitor_rows
    assert event_member_count == 2
    assert len(sent_rows) == 1
    assert "Competitor matches" in caplog.text
    assert "Dedupe decision" in caplog.text
    assert "Telegram delivery" in caplog.text


def test_radar_collection_continues_when_one_source_fails(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_partial.db"
    feed_path = repo_root / "tests" / "fixtures" / "sample_direct_feed.xml"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    good_feed = (
        feed_path.read_text(encoding="utf-8")
        .replace("__FRESH_DATE__", format_datetime(now - timedelta(hours=2)))
        .replace("__STALE_DATE__", format_datetime(now - timedelta(days=14)))
    )

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="broken_feed",
                name="Broken Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://broken.example/feed.xml",
                priority=80,
                tags=("tech",),
            ),
            SourceDefinition(
                id="good_feed",
                name="Good Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://good.example/feed.xml",
                priority=90,
                tags=("robotics", "construction"),
            ),
        )
    )

    def fake_fetch_text(url: str) -> str:
        if "broken" in url:
            raise ValueError("malformed_feed")
        return good_feed

    caplog.set_level("INFO")
    service = RadarService(repo_root=repo_root, registry=registry, fetch_text_fn=fake_fetch_text)
    result = service.run(dry_run=True)

    assert result.failed_sources == 1
    assert result.collected_items == 3
    assert "Source collection failed: id=broken_feed reason=malformed_feed" in caplog.text
