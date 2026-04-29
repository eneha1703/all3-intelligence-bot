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


def test_send_stage_editorial_shaping_skips_thought_leadership(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_editorial.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Flex and Teradyne Robotics expand partnership to scale intelligent automation across global manufacturing</title>
    <link>https://example.com/flex-story</link>
    <description>Flex and Teradyne Robotics are expanding their collaboration to accelerate intelligent automation across global manufacturing.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>good-1</guid>
  </item>
  <item>
    <title>From sci-fi to reality: Physical AI’s future with Dr. Jan Liphardt</title>
    <link>https://example.com/thought-leadership</link>
    <description>Dr. Jan Liphardt discusses the future of robotics and safety in human-robot interactions.</description>
    <pubDate>{format_datetime(now - timedelta(hours=2))}</pubDate>
    <guid>bad-1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="editorial_feed",
                name="Editorial Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/editorial.xml",
                priority=100,
                tags=("robotics", "industrial"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (preview or title, None)

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

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/editorial.xml"
        return feed

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

    assert result.sent_items == 1
    assert len(fake_sender.sent_cards) == 1
    assert "Flex and Teradyne Robotics expand partnership" in fake_sender.sent_cards[0].text

    with sqlite3.connect(db_path) as connection:
        thought_row = connection.execute(
            """
            SELECT send_status, skip_reason
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            ("From sci-fi to reality: Physical AI’s future with Dr. Jan Liphardt",),
        ).fetchone()

    assert thought_row == ("stored_only", "editorial_thought_leadership_without_operational_signal")
    assert "Editorial shaping decision" in caplog.text


def test_radar_does_not_resend_same_canonical_event_across_runs(monkeypatch, tmp_path, caplog) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://direct-a.example/story</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Construction robot startup Kewazo raises funding for rollout</title>
    <link>https://direct-b.example/story</link>
    <description>The funding will support deployment across industrial construction workflows.</description>
    <pubDate>{format_datetime(now - timedelta(minutes=30))}</pubDate>
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
        "https://direct-a.example/feed.xml": first_feed,
        "https://direct-b.example/feed.xml": second_feed,
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

    first_result = service.run(source_id="direct_a", dry_run=False)
    second_result = service.run(source_id="direct_b", dry_run=False)

    assert first_result.sent_items == 1
    assert second_result.sent_items == 0
    assert len(fake_sender.sent_cards) == 1

    with sqlite3.connect(db_path) as connection:
        decision_row = connection.execute(
            """
            SELECT rd.send_status, rd.skip_reason
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            ("Construction robot startup Kewazo raises funding for rollout",),
        ).fetchone()

    assert decision_row == ("skip", "already_sent_canonical_event")
    assert "already_sent_canonical_event" in caplog.text


def test_radar_late_send_stage_dedupes_same_funding_event_without_base_cluster_merge(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_late_send_stage_dedupe.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    feed_a = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>The founders behind a $1.5B food delivery exit just raised $25M from RTP Global for a construction robotics startup</title>
    <link>https://direct-a.example/all3-clickbait</link>
    <description>All3, a construction robotics company, has raised $25 million in a seed round led by RTP Global to expand its robotic construction platform.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    feed_b = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>All3 raises $25M to boost construction productivity with robotics and AI</title>
    <link>https://direct-b.example/all3-direct</link>
    <description>All3 has raised $25 million in a seed round led by RTP Global to scale its robotic construction platform for jobsite productivity.</description>
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
                priority=80,
                tags=("construction", "robotics"),
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
                tags=("construction", "robotics"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The round supports scaling construction robotics deployment.", None)

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
        "https://direct-a.example/feed.xml": feed_a,
        "https://direct-b.example/feed.xml": feed_b,
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
    assert result.canonical_events == 2
    assert result.shortlisted_items == 2
    assert result.sent_items == 1
    assert result.skipped_send_items == 1
    assert len(fake_sender.sent_cards) == 1
    assert "<b>All3 raises $25M to boost construction productivity with robotics and AI</b>" in fake_sender.sent_cards[0].text

    with sqlite3.connect(db_path) as connection:
        suppressed_row = connection.execute(
            """
            SELECT rd.send_status, rd.skip_reason
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            ("The founders behind a $1.5B food delivery exit just raised $25M from RTP Global for a construction robotics startup",),
        ).fetchone()

    assert suppressed_row == ("skip", "duplicate_same_event_shortlist")
    assert "Late send-stage duplicate suppression" in caplog.text


def test_radar_late_send_stage_dedupes_same_partnership_event_without_base_cluster_merge(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_late_send_stage_partnership_dedupe.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    feed_a = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Manufacturing supplier Flex broadens factory automation tie-up with Teradyne Robotics</title>
    <link>https://direct-a.example/flex-direct</link>
    <description>Flex and Teradyne Robotics are expanding their collaboration to scale intelligent automation across global manufacturing.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    feed_b = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Teradyne Robotics partners with Flex to scale intelligent automation across global manufacturing</title>
    <link>https://direct-b.example/flex-partnered</link>
    <description>Teradyne Robotics and Flex are expanding a strategic partnership for intelligent automation in manufacturing.</description>
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
                priority=80,
                tags=("industrial", "robotics"),
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
                tags=("industrial", "robotics"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The partnership expands intelligent automation across manufacturing workflows.", None)

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
        "https://direct-a.example/feed.xml": feed_a,
        "https://direct-b.example/feed.xml": feed_b,
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
    assert result.canonical_events == 2
    assert result.shortlisted_items == 2
    assert result.sent_items == 1
    assert result.skipped_send_items == 1
    assert len(fake_sender.sent_cards) == 1

    with sqlite3.connect(db_path) as connection:
        suppressed_row = connection.execute(
            """
            SELECT rd.send_status, rd.skip_reason
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            ("Manufacturing supplier Flex broadens factory automation tie-up with Teradyne Robotics",),
        ).fetchone()

    assert suppressed_row == ("skip", "duplicate_same_partnership_event_shortlist")
    assert "Late send-stage duplicate suppression" in caplog.text


def test_radar_does_not_resend_same_funding_event_across_runs_with_different_url_and_event_id(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_semantic_funding.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>The founders behind a $1.5B food delivery exit just raised $25M from RTP Global for a construction robotics startup</title>
    <link>https://direct-a.example/all3-clickbait</link>
    <description>All3, a construction robotics company, has raised $25 million in a seed round led by RTP Global to expand its robotic construction platform.</description>
    <pubDate>{format_datetime(now - timedelta(hours=3))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>All3 raises $25M to boost construction productivity with robotics and AI</title>
    <link>https://direct-b.example/all3-direct</link>
    <description>All3 has raised $25 million in a seed round led by RTP Global to scale its robotic construction platform for jobsite productivity.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
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
                priority=80,
                tags=("construction", "robotics"),
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
                tags=("construction", "robotics"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The round supports scaling construction robotics deployment.", None)

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
        "https://direct-a.example/feed.xml": first_feed,
        "https://direct-b.example/feed.xml": second_feed,
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

    first_result = service.run(source_id="direct_a", dry_run=False)
    second_result = service.run(source_id="direct_b", dry_run=False)

    assert first_result.sent_items == 1
    assert second_result.sent_items == 0
    assert len(fake_sender.sent_cards) == 1

    with sqlite3.connect(db_path) as connection:
        decision_row = connection.execute(
            """
            SELECT rd.send_status, rd.skip_reason
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            ("All3 raises $25M to boost construction productivity with robotics and AI",),
        ).fetchone()

    assert decision_row == ("skip", "already_sent_same_funding_event")
    assert "Cross-run funding sent-history suppression" in caplog.text
