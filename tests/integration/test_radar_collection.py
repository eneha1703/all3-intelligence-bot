import json
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from all3_radar.delivery.telegram import TelegramDelivery
from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import ClaudeFinalCardResult, SourceDefinition
from all3_radar.pipeline.radar_service import RadarService, _settings_snapshot
from all3_radar.summarization.claude_final_card_client import ClaudeFinalCardUnavailableError
from all3_radar.summarization.claude_editorial_review_client import (
    ClaudeEditorialReviewResult,
    ClaudeEditorialReviewUnavailableError,
)
from all3_radar.sources.registry import SourceRegistry


def _load_radar_decision_for_title(db_path: Path, title: str) -> tuple[str, str | None, dict, int]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT rd.send_status, rd.skip_reason, rd.signals_json, rd.used_gemini
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            (title,),
        ).fetchone()
    assert row is not None
    return row[0], row[1], json.loads(row[2]), row[3]


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


def test_settings_snapshot_masks_anthropic_key(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("TELEGRAM_ALERT_BOT_TOKEN", "telegram-secret")

    service = RadarService(
        repo_root=repo_root,
        registry=SourceRegistry(()),
    )

    snapshot = _settings_snapshot(service.settings)

    assert snapshot["integrations"]["gemini_api_key"] == "***"
    assert snapshot["integrations"]["anthropic_api_key"] == "***"
    assert snapshot["integrations"]["telegram_alert_bot_token"] == "***"


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
            return (
                "The round supports deployment expansion across construction robotics workflows. "
                "Kewazo is using the capital to scale rollout across factory and jobsite operations.",
                None,
            )

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


def test_sent_telegram_news_is_registered_in_group_message_registry(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_group_registry.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://direct-a.example/story</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
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
                tags=("robotics", "construction"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "The round supports deployment expansion across construction robotics workflows. "
                "Kewazo is using the capital to scale rollout across factory and jobsite operations.",
                None,
            )

    class FakeTelegramSender:
        def send_card(self, card):
            return [
                TelegramDelivery(
                    chat_id="-100123",
                    status="sent",
                    telegram_message_id="321",
                    error_text=None,
                    payload_text=card.text,
                )
            ]

    def fake_fetch_text(url: str) -> str:
        assert url == "https://direct-a.example/feed.xml"
        return feed

    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        telegram_sender=FakeTelegramSender(),
    )
    result = service.run(dry_run=False)

    assert result.sent_items == 1
    with sqlite3.connect(db_path) as connection:
        group_row = connection.execute(
            """
            SELECT chat_id, telegram_message_id, sent_by_bot, message_url, link_count, normalized_item_id
            FROM telegram_group_messages
            """
        ).fetchone()
        link_rows = connection.execute(
            """
            SELECT link_index, url
            FROM telegram_group_message_links
            WHERE chat_id = '-100123' AND telegram_message_id = '321'
            ORDER BY link_index
            """
        ).fetchall()

    assert group_row is not None
    assert group_row[0] == "-100123"
    assert group_row[1] == "321"
    assert group_row[2] == 1
    assert group_row[3] == "https://direct-a.example/story"
    assert group_row[4] == 1
    assert group_row[5] is not None
    assert link_rows == [(0, "https://direct-a.example/story")]


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
            return (
                "The round supports deployment expansion across construction robotics workflows. "
                "Kewazo is using the capital to scale rollout across factory and jobsite operations.",
                None,
            )

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


def test_radar_does_not_resend_xpanner_same_funding_event_across_sources(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_xpanner_semantic_funding.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Exclusive: Xpanner Lands $18M To Offer Automation As A Service To Construction Sites</title>
    <link>https://crunchbase.example/xpanner-18m</link>
    <description>Xpanner, a startup automating construction work through robotics and physical AI technology, has raised $18 million in a Series B round.</description>
    <pubDate>{format_datetime(now - timedelta(hours=4))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Xpanner Secures $18M in Series B Bridge Funding for AI-Powered Construction Automation Platform</title>
    <link>https://aiinsider.example/xpanner-bridge</link>
    <description>Xpanner has secured $18M in Series B bridge funding to expand an AI-powered construction automation platform.</description>
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
            return ("Xpanner raised fresh capital to expand construction automation deployment.", None)

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
            ("Xpanner Secures $18M in Series B Bridge Funding for AI-Powered Construction Automation Platform",),
        ).fetchone()

    assert decision_row == ("skip", "already_sent_same_funding_event")
    assert "Cross-run funding sent-history suppression" in caplog.text


def test_radar_does_not_resend_same_robotic_hand_valuation_story_across_runs(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_linkerbot_valuation.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Report: China Robotic Hand Maker Linkerbot Targets $6B Valuation</title>
    <link>https://ai-insider.example/linkerbot-6b</link>
    <description>Chinese robotics startup Linkerbot is targeting a $6 billion valuation in its next funding round, doubling the valuation it secured in a recently completed financing as investor interest rises around robotic hands for humanoid robots.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Linkerbot hits $3B valuation with Ant Group, HongShan to produce robotic hands that perform delicate tasks</title>
    <link>https://techfundingnews.example/linkerbot-3b</link>
    <description>Chinese robotics startup Linkerbot has closed a Series B+ round at a $3 billion valuation to scale robotic hands for humanoid robots, Reuters reports.</description>
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
                priority=90,
                tags=("robotics", "humanoid"),
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
                priority=90,
                tags=("robotics", "humanoid"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The company is scaling robotic hands for humanoid systems after fresh investor demand.", None)

    class FakeClaudeEditorialReviewClient:
        is_available = True

        def review_candidate(self, **kwargs):
            return ClaudeEditorialReviewResult(
                send_ok=True,
                edited_title=kwargs["title"],
                edited_summary="The company is scaling robotic hands for humanoid systems after fresh investor demand.",
                reject_reason=None,
                confidence="high",
                used_claude=True,
            )

    class FakeClaudeFinalCardClient:
        is_available = True

        def generate_final_card(self, **kwargs):
            return ClaudeFinalCardResult(
                send_ok=True,
                reject_reason=None,
                title=kwargs["title"],
                summary="The company is scaling robotic hands for humanoid systems after fresh investor demand.",
                why_it_matters="Internal only.",
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )

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
        claude_editorial_review_client=FakeClaudeEditorialReviewClient(),
        claude_final_card_client=FakeClaudeFinalCardClient(),
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
            ("Linkerbot hits $3B valuation with Ant Group, HongShan to produce robotic hands that perform delicate tasks",),
        ).fetchone()

    assert decision_row == ("skip", "already_sent_same_funding_event")
    assert "Cross-run funding sent-history suppression" in caplog.text


def test_radar_does_not_resend_same_deployment_event_across_runs_with_different_url_and_event_id(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_semantic_deployment.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</title>
    <link>https://direct-a.example/hexagon-schaeffler-aeon</link>
    <description>Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoid robots across factories worldwide.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Schaeffler confirms deployment of 1,000 Hexagon humanoid robots by 2032</title>
    <link>https://direct-b.example/schaeffler-hexagon-deploys</link>
    <description>Schaeffler said the deployment will place 1,000 Hexagon humanoid robots across its global factory operations and industrial manufacturing sites by 2032.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
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
                tags=("robotics", "industrial"),
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
                tags=("robotics", "industrial"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The deployment expands humanoid rollout across industrial operations.", None)

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
            ("Schaeffler confirms deployment of 1,000 Hexagon humanoid robots by 2032",),
        ).fetchone()

    assert decision_row == ("skip", "already_sent_same_deployment_event")
    assert "Cross-run deployment sent-history suppression" in caplog.text


def test_radar_allows_same_deployment_entities_with_different_quantity_across_runs(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_semantic_deployment_quantity.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</title>
    <link>https://direct-a.example/hexagon-schaeffler-aeon</link>
    <description>Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoid robots across factories worldwide.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Schaeffler confirms deployment of 500 Hexagon humanoid robots by 2032</title>
    <link>https://direct-b.example/schaeffler-hexagon-500</link>
    <description>Schaeffler said the deployment will place 500 Hexagon humanoid robots across its global factory operations and industrial manufacturing sites by 2032.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
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
                tags=("robotics", "industrial"),
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
                tags=("robotics", "industrial"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The deployment expands humanoid rollout across industrial operations.", None)

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
    assert second_result.sent_items == 1
    assert len(fake_sender.sent_cards) == 2


def test_radar_allows_different_deployment_entities_with_same_quantity_across_runs(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_semantic_deployment_entities.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</title>
    <link>https://direct-a.example/hexagon-schaeffler-aeon</link>
    <description>Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoid robots across factories worldwide.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>ABB and SKF to install 1,000 Aeon humanoid robots across factory sites</title>
    <link>https://direct-b.example/abb-skf-aeon</link>
    <description>ABB and SKF said the rollout will deploy 1,000 Aeon humanoid robots across industrial factory and manufacturing sites.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
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
                tags=("robotics", "industrial"),
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
                tags=("robotics", "industrial"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The deployment expands humanoid rollout across industrial operations.", None)

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
    assert second_result.sent_items == 1
    assert len(fake_sender.sent_cards) == 2


def test_radar_does_not_skip_non_deployment_strategy_article_across_runs(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_repeat_semantic_deployment_strategy.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    now = datetime.now(timezone.utc)
    first_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</title>
    <link>https://direct-a.example/hexagon-schaeffler-aeon</link>
    <description>Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoid robots across factories worldwide.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""
    second_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>How humanoid robotics strategy is evolving in Europe</title>
    <link>https://direct-b.example/humanoid-strategy</link>
    <description>A strategy article on how manufacturers are thinking about the humanoid market over the next decade.</description>
    <pubDate>{format_datetime(now - timedelta(hours=6))}</pubDate>
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
                tags=("robotics", "industrial"),
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
                tags=("robotics", "industrial"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("The deployment expands humanoid rollout across industrial operations.", None)

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
            ("How humanoid robotics strategy is evolving in Europe",),
        ).fetchone()

    assert decision_row != ("skip", "already_sent_same_deployment_event")


def test_claude_final_card_disabled_preserves_current_behavior_without_calling_client(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_disabled.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "false")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_disabled_feed",
                name="Claude Disabled Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-disabled.xml",
                priority=100,
                tags=("robotics", "construction"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "The round supports deployment expansion across construction robotics workflows. "
                "Kewazo is using the capital to scale rollout across factory and jobsite operations.",
                None,
            )

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

    class FakeClaudeClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def generate_final_card(self, **kwargs):
            self.call_count += 1
            raise AssertionError("Claude client should not be called when disabled")

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-disabled.xml"
        return feed

    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 0
    assert len(fake_sender.sent_cards) == 1
    assert "<b>Kewazo raises funding for construction robot rollout</b>" in fake_sender.sent_cards[0].text
    send_status, skip_reason, signals, _ = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert signals["claude_editorial_reviewed"] is False
    assert signals["claude_editorial_outcome"] == "not_reviewed"
    assert signals["claude_editorial_not_reviewed_reason"] == "disabled"
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 1
    assert signals["card_writer"] == "gemini_summary"
    assert signals["final_card_title_source"] == "original_title"
    assert signals["final_card_summary_source"] == "gemini_summary"
    assert signals["claude_final_card_reviewed"] is False
    assert signals["claude_final_card_outcome"] == "not_attempted"
    assert signals["claude_final_card_reason"] is None


def test_claude_final_card_success_updates_final_card_and_stage_counters(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_success.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_success_feed",
                name="Claude Success Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-success.xml",
                priority=100,
                tags=("robotics", "construction"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "The round supports deployment expansion across construction robotics workflows. "
                "Kewazo is using the capital to scale rollout across factory and jobsite operations.",
                None,
            )

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

    class FakeClaudeClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def generate_final_card(self, **kwargs):
            self.call_count += 1
            return ClaudeFinalCardResult(
                send_ok=True,
                reject_reason=None,
                title="Claude edited headline",
                summary="Kewazo raised funding to scale construction robot deployments across factory and jobsite operations.",
                why_it_matters="Internal only.",
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )

    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-success.xml"
        return feed

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 1
    assert "<b>Claude edited headline</b>" in fake_sender.sent_cards[0].text
    assert "Kewazo raised funding to scale construction robot deployments" in fake_sender.sent_cards[0].text
    assert captured_stage_counters["claude_final_card_attempted"] == 1
    assert captured_stage_counters["claude_final_card_used"] == 1
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 1
    assert signals["card_writer"] == "claude_final_card"
    assert signals["final_card_title_source"] == "claude_final_card"
    assert signals["final_card_summary_source"] == "claude_final_card"
    assert signals["claude_final_card_reviewed"] is True
    assert signals["claude_final_card_outcome"] == "rewritten"
    assert signals["claude_final_card_reason"] is None


def test_claude_final_card_rejection_marks_stored_only_and_skips_send(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_reject.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_reject_feed",
                name="Claude Reject Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-reject.xml",
                priority=100,
                tags=("robotics", "construction"),
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
            return []

    class FakeClaudeClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def generate_final_card(self, **kwargs):
            self.call_count += 1
            return ClaudeFinalCardResult(
                send_ok=False,
                reject_reason="generic",
                title=None,
                summary=None,
                why_it_matters=None,
                duplicate_risk="medium",
                confidence="high",
                used_claude=True,
            )

    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-reject.xml"
        return feed

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 0
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 0
    assert captured_stage_counters["claude_final_card_attempted"] == 1
    assert captured_stage_counters["claude_final_card_rejected"] == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT rd.send_status, rd.skip_reason
            FROM radar_decisions rd
            JOIN normalized_items ni ON ni.id = rd.normalized_item_id
            WHERE ni.title = ?
            """,
            ("Kewazo raises funding for construction robot rollout",),
        ).fetchone()

    assert row == ("stored_only", "claude_final_card_rejected")


def test_robot_data_infrastructure_story_skips_claude_final_card_rejection_path(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_skip_robot_data.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Tutor Intelligence builds Data Factory to train robot AI in the real world</title>
    <link>https://example.com/tutor</link>
    <description>Tutor Intelligence is running 100 Sonny semi-humanoid robots while sharing real-world data with its mobile manipulator platform.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="robot_data_feed",
                name="Robot Data Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/robot-data.xml",
                priority=100,
                tags=("robotics",),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "Tutor Intelligence is running 100 Sonny semi-humanoid robots and using the fleet to collect real-world data for its mobile manipulator platform. "
                "The setup turns live robot operations into a data factory for training robot AI in production-like conditions.",
                None,
            )

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

    class FakeClaudeClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def generate_final_card(self, **kwargs):
            self.call_count += 1
            return ClaudeFinalCardResult(
                send_ok=False,
                reject_reason="internal_r_and_d_story",
                title=None,
                summary=None,
                why_it_matters=None,
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/robot-data.xml"
        return feed

    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 0
    assert len(fake_sender.sent_cards) == 1
    assert "Tutor Intelligence builds Data Factory to train robot AI in the real world" in fake_sender.sent_cards[0].text
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Tutor Intelligence builds Data Factory to train robot AI in the real world"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 1
    assert signals["claude_final_card_reviewed"] is False
    assert signals["claude_final_card_outcome"] == "not_attempted"
    assert signals["claude_final_card_reason"] == "specialized_robot_data_infrastructure_passthrough"


def test_uk_construction_market_story_skips_claude_final_card_rejection_path(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_skip_uk_market.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Double whammy hits April construction output</title>
    <link>https://example.com/double-whammy</link>
    <description>A combination of lower activity and higher inflation has resulted in the steepest monthly decline in UK construction output since last November.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="construction_news_intelligence_listing",
                name="Construction News Intelligence",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/uk-market.xml",
                priority=100,
                tags=("construction", "uk", "market"),
                extra_config={"market_scope": "uk_construction_market"},
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "UK construction output posted its steepest monthly decline since November as lower activity combined with higher inflation. "
                "The update points to continued pressure across the UK construction market rather than a one-off sector move.",
                None,
            )

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

    class FakeClaudeClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def generate_final_card(self, **kwargs):
            self.call_count += 1
            return ClaudeFinalCardResult(
                send_ok=False,
                reject_reason="generic_market_stat",
                title=None,
                summary=None,
                why_it_matters=None,
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/uk-market.xml"
        return feed

    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 1
    assert "Double whammy hits April construction output" in fake_sender.sent_cards[0].text
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Double whammy hits April construction output"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 1
    assert signals["claude_final_card_reviewed"] is True
    assert signals["claude_final_card_outcome"] == "fallback_protected_market_signal"
    assert signals["claude_final_card_reason"] == "generic_market_stat"


def test_transport_framework_story_is_not_protected_from_claude_final_card_rejection(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_transport_framework_reject.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Three firms get places on £700m London transport framework</title>
    <link>https://example.com/tfl-framework</link>
    <description>Amey, Costain and Dragados have won places on Transport for London's infrastructure improvement framework, worth up to £700m.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="construction_news_intelligence_listing",
                name="Construction News Intelligence",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/tfl-framework.xml",
                priority=100,
                tags=("construction", "uk", "market"),
                extra_config={"market_scope": "uk_construction_market"},
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "Amey, Costain and Dragados have won places on a TfL transport framework worth up to £700m.",
                None,
            )

    class FakeTelegramSender:
        def __init__(self) -> None:
            self.sent_cards = []

        def send_card(self, card):
            self.sent_cards.append(card)
            return []

    class FakeClaudeClient:
        is_available = True

        def generate_final_card(self, **kwargs):
            return ClaudeFinalCardResult(
                send_ok=False,
                reject_reason="generic_transport_framework",
                title=None,
                summary=None,
                why_it_matters=None,
                duplicate_risk="low",
                confidence="high",
                used_claude=True,
            )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/tfl-framework.xml"
        return feed

    fake_sender = FakeTelegramSender()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=FakeClaudeClient(),
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 0
    assert len(fake_sender.sent_cards) == 0
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Three firms get places on £700m London transport framework"
    )
    assert send_status == "stored_only"
    assert skip_reason == "claude_final_card_rejected"
    assert signals["claude_final_card_outcome"] == "rejected"
    assert signals["claude_final_card_reason"] == "generic_transport_framework"


def test_claude_final_card_invalid_output_is_not_sent(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_invalid_output.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_invalid_output_feed",
                name="Claude Invalid Output Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/kewazo.xml",
                priority=100,
                tags=("robotics", "construction"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "Kewazo says the round supports deployment expansion across construction robotics workflows.",
                None,
            )

    class FakeTelegramSender:
        def __init__(self) -> None:
            self.sent_cards = []

        def send_card(self, card):
            self.sent_cards.append(card)
            return []

    class FakeClaudeClient:
        is_available = True

        def generate_final_card(self, **kwargs):
            raise ClaudeFinalCardUnavailableError("Claude final-card response summary must not contain raw URLs.")

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/kewazo.xml"
        return feed

    fake_sender = FakeTelegramSender()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=FakeClaudeClient(),
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 0
    assert len(fake_sender.sent_cards) == 0
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "stored_only"
    assert skip_reason == "claude_final_card_invalid_output"
    assert signals["claude_final_card_outcome"] == "rejected_invalid_output"


def test_claude_final_card_failure_falls_back_to_deterministic_send_and_cap(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_fallback_cap.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_FINAL_CARD_MAX_CANDIDATES", "1")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
  <item>
    <title>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</title>
    <link>https://example.com/hexagon</link>
    <description>Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoid robots across factories worldwide.</description>
    <pubDate>{format_datetime(now - timedelta(hours=2))}</pubDate>
    <guid>b1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_fallback_feed",
                name="Claude Fallback Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-fallback.xml",
                priority=100,
                tags=("robotics", "construction"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "Kewazo says the round supports deployment expansion across construction robotics workflows. "
                "The company is using the capital to scale rollout across factory and jobsite operations.",
                None,
            )

    class FakeTelegramSender:
        def __init__(self) -> None:
            self.sent_cards = []

        def send_card(self, card):
            self.sent_cards.append(card)
            return [
                TelegramDelivery(
                    chat_id="123",
                    status="sent",
                    telegram_message_id=f"msg-{len(self.sent_cards)}",
                    error_text=None,
                    payload_text=card.text,
                )
            ]

    class FakeClaudeClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def generate_final_card(self, **kwargs):
            self.call_count += 1
            raise ClaudeFinalCardUnavailableError("invalid_json")

    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-fallback.xml"
        return feed

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_final_card_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 2
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 2
    assert "<b>Kewazo raises funding for construction robot rollout</b>" in fake_sender.sent_cards[0].text
    assert "<b>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</b>" in fake_sender.sent_cards[1].text
    assert captured_stage_counters["claude_final_card_attempted"] == 1
    assert captured_stage_counters["claude_final_card_fallback"] == 1
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 1
    assert signals["claude_final_card_reviewed"] is True
    assert signals["claude_final_card_outcome"] == "fallback_unavailable"
    assert signals["claude_final_card_reason"] == "invalid_json"
    assert signals["card_writer"] == "deterministic_after_claude_final_card_fallback"
    assert signals["final_card_title_source"] == "original_title"
    assert signals["final_card_summary_source"] == "gemini_summary"


def test_deterministic_fallback_summary_records_card_writer_diagnostics(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_deterministic_summary.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "false")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="deterministic_summary_feed",
                name="Deterministic Summary Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/deterministic-summary.xml",
                priority=100,
                tags=("robotics", "construction"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = False

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
        assert url == "https://example.com/deterministic-summary.xml"
        return feed

    fake_sender = FakeTelegramSender()
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
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 0
    assert signals["card_writer"] == "deterministic_summary"
    assert signals["final_card_title_source"] == "original_title"
    assert signals["final_card_summary_source"] == "deterministic_summary"
    assert signals["claude_final_card_reviewed"] is False
    assert signals["claude_final_card_outcome"] == "not_attempted"
    assert signals["claude_final_card_reason"] is None


def test_claude_editorial_disabled_preserves_current_behavior_without_calling_client(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_editorial_disabled.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "false")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_disabled_feed",
                name="Claude Editorial Disabled Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-disabled.xml",
                priority=100,
                tags=("robotics", "construction"),
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

    class FakeClaudeEditorialClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def review_candidate(self, **kwargs):
            self.call_count += 1
            raise AssertionError("Claude editorial client should not be called when disabled")

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-editorial-disabled.xml"
        return feed

    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeEditorialClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 0
    assert len(fake_sender.sent_cards) == 1
    assert "<b>Kewazo raises funding for construction robot rollout</b>" in fake_sender.sent_cards[0].text


def test_claude_editorial_high_confidence_promotion_sends_below_threshold_story(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_db_path = tmp_path / "radar_claude_editorial_promotion_baseline.db"
    db_path = tmp_path / "radar_claude_editorial_promotion.db"
    monkeypatch.setenv("DATABASE_PATH", str(baseline_db_path))

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>SoftBank backs robotics startup Roze for data center construction automation</title>
    <link>https://example.com/softbank-roze</link>
    <description>Roze is building robotics and automation systems for data center construction and physical infrastructure delivery.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_promote_feed",
                name="Claude Editorial Promote Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-promote.xml",
                priority=100,
                tags=("robotics", "construction", "infrastructure"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return ("Roze is building robotics and automation systems for data center construction.", None)

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

    class FakeClaudeEditorialClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def review_candidate(self, **kwargs):
            self.call_count += 1
            return ClaudeEditorialReviewResult(
                send_ok=True,
                reject_reason=None,
                edited_title="SoftBank-backed Roze automates data center construction",
                edited_summary="Roze is applying robotics to speed data center construction.",
                confidence="high",
                used_claude=True,
            )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-editorial-promote.xml"
        return feed

    baseline_sender = FakeTelegramSender()
    baseline_service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        telegram_sender=baseline_sender,
    )
    baseline_result = baseline_service.run(dry_run=False)
    assert baseline_result.sent_items == 0

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")
    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeEditorialClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 1
    assert "<b>SoftBank-backed Roze automates data center construction</b>" in fake_sender.sent_cards[0].text
    assert captured_stage_counters["claude_editorial_attempted"] == 1
    assert captured_stage_counters["claude_editorial_promoted"] == 1
    send_status, skip_reason, signals, used_gemini = _load_radar_decision_for_title(
        db_path, "SoftBank backs robotics startup Roze for data center construction automation"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert used_gemini == 0
    assert signals["claude_editorial_reviewed"] is True
    assert signals["claude_editorial_review_rank"] == 1
    assert signals["claude_editorial_outcome"] == "promoted"
    assert signals["claude_editorial_confidence"] == "high"
    assert signals["claude_editorial_reason"] is None
    assert signals["claude_editorial_send_ok"] is True
    assert signals["claude_editorial_has_edited_title"] is True
    assert signals["claude_editorial_has_edited_summary"] is True
    assert signals["claude_editorial_has_reject_reason"] is False
    assert signals["claude_editorial_not_reviewed_reason"] is None
    assert signals["card_writer"] == "claude_editorial_promotion"
    assert signals["final_card_title_source"] == "claude_editorial_promotion"
    assert signals["final_card_summary_source"] == "claude_editorial_promotion"
    assert signals["claude_final_card_reviewed"] is False
    assert signals["claude_final_card_outcome"] == "not_attempted"
    assert signals["claude_final_card_reason"] is None


def test_claude_editorial_high_confidence_rejection_blocks_subtle_false_positive(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_db_path = tmp_path / "radar_claude_editorial_reject_baseline.db"
    db_path = tmp_path / "radar_claude_editorial_reject.db"
    monkeypatch.setenv("DATABASE_PATH", str(baseline_db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Taco Bell deploys physical AI robotics platform across restaurant kitchens</title>
    <link>https://example.com/taco-bell-ai</link>
    <description>The rollout adds kitchen robotics, AI drive-thru ordering, and menu personalization across Taco Bell locations.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_reject_feed",
                name="Claude Editorial Reject Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-reject.xml",
                priority=100,
                tags=("automation", "ai"),
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

    class FakeClaudeEditorialClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def review_candidate(self, **kwargs):
            self.call_count += 1
            return ClaudeEditorialReviewResult(
                send_ok=False,
                reject_reason="consumer_ai_menu_personalization",
                edited_title=None,
                edited_summary=None,
                confidence="high",
                used_claude=True,
            )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-editorial-reject.xml"
        return feed

    baseline_sender = FakeTelegramSender()
    baseline_service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        telegram_sender=baseline_sender,
    )
    baseline_result = baseline_service.run(dry_run=False)
    assert baseline_result.sent_items == 1

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeEditorialClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 0
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 0
    assert captured_stage_counters["claude_editorial_attempted"] == 1
    assert captured_stage_counters["claude_editorial_rejected"] == 1

    send_status, skip_reason, signals, _ = _load_radar_decision_for_title(
        db_path, "Taco Bell deploys physical AI robotics platform across restaurant kitchens"
    )
    assert (send_status, skip_reason) == ("stored_only", "claude_editorial_rejected")
    assert signals["claude_editorial_reviewed"] is True
    assert signals["claude_editorial_review_rank"] == 1
    assert signals["claude_editorial_outcome"] == "rejected"
    assert signals["claude_editorial_confidence"] == "high"
    assert signals["claude_editorial_reason"] == "consumer_ai_menu_personalization"
    assert signals["claude_editorial_send_ok"] is False
    assert signals["claude_editorial_has_edited_title"] is False
    assert signals["claude_editorial_has_edited_summary"] is False
    assert signals["claude_editorial_has_reject_reason"] is True
    assert signals["claude_editorial_reject_reason"] == "consumer_ai_menu_personalization"
    assert signals["claude_editorial_not_reviewed_reason"] is None


def test_claude_editorial_unavailable_falls_back_to_old_deterministic_behavior(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_editorial_fallback.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_fallback_feed",
                name="Claude Editorial Fallback Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-fallback.xml",
                priority=100,
                tags=("robotics", "construction"),
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

    class FakeClaudeEditorialClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def review_candidate(self, **kwargs):
            self.call_count += 1
            raise ClaudeEditorialReviewUnavailableError(
                "api_http_error",
                "Claude request failed with HTTP error.",
                status_code=400,
            )

    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-editorial-fallback.xml"
        return feed

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    caplog.set_level("WARNING")
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeEditorialClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 1
    assert captured_stage_counters["claude_editorial_attempted"] == 1
    assert captured_stage_counters["claude_editorial_fallback"] == 1
    assert captured_stage_counters["claude_editorial_fallback_api_http_error"] == 1
    assert (
        'Claude editorial fallback: reason=api_http_error status=400 title="Kewazo raises funding for construction robot rollout" source="Claude Editorial Fallback Feed"'
        in caplog.text
    )
    send_status, skip_reason, signals, _ = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert signals["claude_editorial_reviewed"] is True
    assert signals["claude_editorial_review_rank"] == 1
    assert signals["claude_editorial_outcome"] == "fallback_unavailable"
    assert signals["claude_editorial_confidence"] is None
    assert signals["claude_editorial_reason"] == "api_http_error"
    assert signals["claude_editorial_not_reviewed_reason"] is None


def test_claude_editorial_cap_is_respected(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_editorial_cap.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_EDITORIAL_MAX_CANDIDATES", "1")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
  <item>
    <title>Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network</title>
    <link>https://example.com/hexagon</link>
    <description>Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoid robots across factories worldwide.</description>
    <pubDate>{format_datetime(now - timedelta(hours=2))}</pubDate>
    <guid>b1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_cap_feed",
                name="Claude Editorial Cap Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-cap.xml",
                priority=100,
                tags=("robotics", "construction"),
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
                    telegram_message_id=f"msg-{len(self.sent_cards)}",
                    error_text=None,
                    payload_text=card.text,
                )
            ]

    class FakeClaudeEditorialClient:
        is_available = True

        def __init__(self) -> None:
            self.call_count = 0

        def review_candidate(self, **kwargs):
            self.call_count += 1
            return ClaudeEditorialReviewResult(
                send_ok=True,
                reject_reason=None,
                edited_title="Needs deterministic control",
                edited_summary="Claude reviewed this candidate but did not have high confidence to override.",
                confidence="medium",
                used_claude=True,
            )

    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-editorial-cap.xml"
        return feed

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)
    caplog.set_level("WARNING")
    fake_sender = FakeTelegramSender()
    fake_claude = FakeClaudeEditorialClient()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=fake_claude,
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 2
    assert fake_claude.call_count == 1
    assert len(fake_sender.sent_cards) == 2
    assert captured_stage_counters["claude_editorial_attempted"] == 1
    assert captured_stage_counters["claude_editorial_fallback"] == 1
    assert captured_stage_counters["claude_editorial_fallback_low_or_medium_confidence"] == 1
    assert "Claude editorial fallback: reason=low_or_medium_confidence confidence=medium" in caplog.text
    kewazo_status, kewazo_skip_reason, kewazo_signals, _ = _load_radar_decision_for_title(
        db_path, "Kewazo raises funding for construction robot rollout"
    )
    assert kewazo_status == "sent"
    assert kewazo_skip_reason is None
    assert kewazo_signals["claude_editorial_reviewed"] is True
    assert kewazo_signals["claude_editorial_review_rank"] == 1
    assert kewazo_signals["claude_editorial_outcome"] == "fallback_low_or_medium_confidence"
    assert kewazo_signals["claude_editorial_confidence"] == "medium"
    assert kewazo_signals["claude_editorial_reason"] == "low_or_medium_confidence"
    assert kewazo_signals["claude_editorial_send_ok"] is True
    assert kewazo_signals["claude_editorial_has_edited_title"] is True
    assert kewazo_signals["claude_editorial_has_edited_summary"] is True
    assert kewazo_signals["claude_editorial_has_reject_reason"] is False
    assert kewazo_signals["claude_editorial_not_reviewed_reason"] is None
    hexagon_status, hexagon_skip_reason, hexagon_signals, _ = _load_radar_decision_for_title(
        db_path, "Hexagon and Schaeffler to install 1,000 Aeon humanoid robots across global factory network"
    )
    assert hexagon_status == "sent"
    assert hexagon_skip_reason is None
    assert hexagon_signals["claude_editorial_reviewed"] is False
    assert hexagon_signals["claude_editorial_outcome"] == "not_reviewed"
    assert hexagon_signals["claude_editorial_not_reviewed_reason"] == "over_max_candidates_cap"


def test_claude_editorial_medium_rejection_records_send_ok_and_reject_reason(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_editorial_medium_reject.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Industrial robotics startup raises new funding for deployment</title>
    <link>https://example.com/robotics-medium-reject</link>
    <description>The company raised new funding for robotics deployment across industrial sites.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>medium-reject-1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_medium_reject_feed",
                name="Claude Editorial Medium Reject Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-medium-reject.xml",
                priority=100,
                tags=("robotics", "industrial"),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = True

        def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
            return (
                "The funding supports industrial robotics deployment across production sites.",
                None,
            )

    class FakeClaudeEditorialClient:
        is_available = True

        def review_candidate(self, **kwargs):
            return ClaudeEditorialReviewResult(
                send_ok=False,
                reject_reason="interesting_but_not_strong_enough",
                edited_title=None,
                edited_summary=None,
                confidence="medium",
                used_claude=True,
            )

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
        assert url == "https://example.com/claude-editorial-medium-reject.xml"
        return feed

    fake_sender = FakeTelegramSender()
    caplog.set_level("INFO")
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=FakeClaudeEditorialClient(),
        telegram_sender=fake_sender,
    )

    result = service.run(dry_run=False)

    assert result.sent_items == 1
    assert len(fake_sender.sent_cards) == 1
    send_status, skip_reason, signals, _ = _load_radar_decision_for_title(
        db_path, "Industrial robotics startup raises new funding for deployment"
    )
    assert send_status == "sent"
    assert skip_reason is None
    assert signals["claude_editorial_reviewed"] is True
    assert signals["claude_editorial_outcome"] == "fallback_low_or_medium_confidence"
    assert signals["claude_editorial_confidence"] == "medium"
    assert signals["claude_editorial_send_ok"] is False
    assert signals["claude_editorial_has_edited_title"] is False
    assert signals["claude_editorial_has_edited_summary"] is False
    assert signals["claude_editorial_has_reject_reason"] is True
    assert signals["claude_editorial_reject_reason"] == "interesting_but_not_strong_enough"


def _run_claude_editorial_single_case(
    monkeypatch,
    tmp_path,
    *,
    slug: str,
    title: str,
    description: str,
    tags: tuple[str, ...],
    claude_result: ClaudeEditorialReviewResult,
    source_id: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    source_priority: int = 100,
    item_link: str | None = None,
) -> tuple[object, object, list, str, str | None, dict]:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_db_path = tmp_path / f"{slug}_baseline.db"
    db_path = tmp_path / f"{slug}.db"
    monkeypatch.setenv("DATABASE_PATH", str(baseline_db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "false")
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "false")

    now = datetime.now(timezone.utc)
    resolved_source_id = source_id or f"{slug}_feed"
    resolved_source_name = source_name or f"{slug} Feed"
    resolved_source_url = source_url or f"https://example.com/{slug}.xml"
    resolved_item_link = item_link or f"https://example.com/{slug}"
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>{title}</title>
    <link>{resolved_item_link}</link>
    <description>{description}</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>{slug}-1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id=resolved_source_id,
                name=resolved_source_name,
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url=resolved_source_url,
                priority=source_priority,
                tags=tags,
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
                    telegram_message_id=f"msg-{len(self.sent_cards)}",
                    error_text=None,
                    payload_text=card.text,
                )
            ]

    class FakeClaudeEditorialClient:
        is_available = True

        def review_candidate(self, **kwargs):
            return claude_result

    def fake_fetch_text(url: str) -> str:
        assert url == resolved_source_url
        return feed

    baseline_sender = FakeTelegramSender()
    baseline_service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        telegram_sender=baseline_sender,
    )
    baseline_result = baseline_service.run(dry_run=False)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")
    fake_sender = FakeTelegramSender()
    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=FakeClaudeEditorialClient(),
        telegram_sender=fake_sender,
    )
    result = service.run(dry_run=False)
    send_status, skip_reason, signals, _ = _load_radar_decision_for_title(db_path, title)
    return baseline_result, result, fake_sender.sent_cards, send_status, skip_reason, signals


def test_claude_editorial_medium_promotion_promotes_top_taxonomy_buckets(
    monkeypatch, tmp_path
) -> None:
    teradyne_baseline, teradyne_result, teradyne_cards, teradyne_status, teradyne_skip_reason, teradyne_signals = _run_claude_editorial_single_case(
        monkeypatch,
        tmp_path,
        slug="medium-teradyne",
        title="Robotics segment revenue rises at the start of 2026",
        description="Teradyne Robotics brought in $91 million in Q1 2026, with its AI products helping to boost robotics sales.",
        tags=("robotics", "industrial"),
        claude_result=ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title="Teradyne Robotics revenue rises as industrial automation demand builds",
            edited_summary="Teradyne Robotics reported stronger segment revenue, pointing to continued demand for industrial automation systems.",
            confidence="medium",
            used_claude=True,
        ),
    )
    assert teradyne_baseline.sent_items == 0
    assert teradyne_result.sent_items == 1
    assert len(teradyne_cards) == 1
    assert teradyne_status == "sent"
    assert teradyne_skip_reason is None
    assert teradyne_signals["claude_editorial_outcome"] == "promoted"
    assert teradyne_signals["claude_editorial_confidence"] == "medium"
    assert teradyne_signals["claude_editorial_medium_promoted"] is True

    launchpad_baseline, launchpad_result, launchpad_cards, launchpad_status, launchpad_skip_reason, launchpad_signals = _run_claude_editorial_single_case(
        monkeypatch,
        tmp_path,
        slug="medium-launchpad",
        title="Manufacturing language model helps engineers outline automation workflows",
        description="The tool is positioned as an aid for factory automation engineering teams to outline cell designs and programming tasks, without reporting customer deployments, scale metrics, or commissioning results.",
        tags=("robotics", "industrial"),
        source_id="robot_report_rss",
        source_name="The Robot Report RSS",
        source_url="https://robot-report.example/medium-launchpad.xml",
        source_priority=85,
        claude_result=ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title="Manufacturing language model targets industrial automation engineering",
            edited_summary="The tool is aimed at speeding automation design, programming, and deployment engineering for factory systems.",
            confidence="medium",
            used_claude=True,
        ),
    )
    assert launchpad_baseline.sent_items == 0
    assert launchpad_result.sent_items == 1
    assert len(launchpad_cards) == 1
    assert launchpad_status == "sent"
    assert launchpad_skip_reason is None
    assert launchpad_signals["claude_editorial_outcome"] == "promoted"
    assert launchpad_signals["claude_editorial_confidence"] == "medium"
    assert launchpad_signals["claude_editorial_medium_promoted"] is True

    roze_baseline, roze_result, roze_cards, roze_status, roze_skip_reason, roze_signals = _run_claude_editorial_single_case(
        monkeypatch,
        tmp_path,
        slug="medium-roze",
        title="Robotics-led infrastructure venture targets data center buildout",
        description="The venture combines robotics, data center construction, and physical AI platform ambitions for infrastructure delivery.",
        tags=("robotics", "construction", "infrastructure"),
        claude_result=ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title="Robotics-led infrastructure venture targets data center buildout",
            edited_summary="The company is positioning robotics and physical AI as part of how data center capacity gets built.",
            confidence="medium",
            used_claude=True,
        ),
    )
    assert roze_baseline.sent_items == 1
    assert roze_result.sent_items == 1
    assert len(roze_cards) == 1
    assert roze_status == "sent"
    assert roze_skip_reason is None
    assert roze_signals["claude_editorial_outcome"] == "promoted"
    assert roze_signals["claude_editorial_confidence"] == "medium"
    assert roze_signals["claude_editorial_medium_promoted"] is True


def test_claude_editorial_medium_promotion_does_not_apply_to_reviewed_non_top_taxonomy_buckets(
    monkeypatch, tmp_path
) -> None:
    cases = [
        (
            "medium-greenhouse",
            "Omni-directional trolley positions greenhouse automation for harvesting robots",
            "The German agritech startup calls the trolley a robot-ready stepping stone to greenhouse automation, fully-automated greenhouses, and harvesting robots for industrial greenhouse operations.",
            ("automation",),
            "robotics_automation_news_rss",
            "Robotics and Automation News RSS",
            "https://robotics-automation.example/medium-greenhouse.xml",
            80,
            None,
        ),
        (
            "medium-procurement",
            "How Procurement Automation Creates Audit-Ready Supply Chains in Manufacturing",
            "A tier-two automotive supplier used procurement automation to improve approval history and audit-ready supply chain workflows.",
            ("automation",),
            "robotics_automation_news_rss",
            "Robotics and Automation News RSS",
            "https://robotics-automation.example/medium-procurement.xml",
            80,
            None,
        ),
        (
            "medium-security",
            "How Access Control Systems Integrate with Industrial IoT for Real-Time Security Automation",
            "Factories and logistics hubs are using connected sensors and access control systems for real-time security automation in industrial IoT environments.",
            ("automation",),
            "robotics_automation_news_rss",
            "Robotics and Automation News RSS",
            "https://robotics-automation.example/medium-security.xml",
            80,
            None,
        ),
        (
            "medium-auction",
            "Surplus robots, robot welders, and support equipment to be auctioned by BTM Industrial",
            "BTM Industrial is liquidating surplus inventory and auctioning robot welders and support equipment to free up floor space.",
            ("automation",),
            "robotics_automation_news_rss",
            "Robotics and Automation News RSS",
            "https://robotics-automation.example/medium-auction.xml",
            80,
            None,
        ),
    ]

    for slug, title, description, tags, source_id, source_name, source_url, source_priority, item_link in cases:
        baseline_result, result, sent_cards, send_status, skip_reason, signals = _run_claude_editorial_single_case(
            monkeypatch,
            tmp_path,
            slug=slug,
            title=title,
            description=description,
            tags=tags,
            source_id=source_id,
            source_name=source_name,
            source_url=source_url,
            source_priority=source_priority,
            item_link=item_link,
            claude_result=ClaudeEditorialReviewResult(
                send_ok=True,
                reject_reason=None,
                edited_title=f"Edited {title}",
                edited_summary="Edited summary suggesting the story might be worth sending.",
                confidence="medium",
                used_claude=True,
            ),
        )
        assert signals["claude_editorial_reviewed"] is True
        assert signals["claude_editorial_send_ok"] is True
        assert signals["claude_editorial_has_edited_title"] is True
        assert signals["claude_editorial_has_edited_summary"] is True
        assert signals["claude_editorial_outcome"] == "fallback_low_or_medium_confidence"
        assert signals["claude_editorial_confidence"] == "medium"
        assert signals.get("claude_editorial_medium_promoted") is not True
        assert baseline_result.sent_items == 0
        assert result.sent_items == 0
        assert len(sent_cards) == result.sent_items
        assert send_status in {"stored_only", "skip"}
        assert skip_reason in {None, "editorial_not_telegram_worthy", "no_clear_all3_scope"}


def test_claude_editorial_medium_promotion_does_not_apply_to_deprioritized_waymo_candidate(
    monkeypatch, tmp_path
) -> None:
    baseline_result, result, sent_cards, send_status, skip_reason, signals = _run_claude_editorial_single_case(
        monkeypatch,
        tmp_path,
        slug="medium-waymo",
        title="Waymo, Alphabet's robotaxi service, is growing fast. Here's how to ride, costs, and the self-driving cars' crash record.",
        description="Waymo is Alphabet's robotaxi service. It has partnered with Uber and DoorDash, launched public rides across cities, worked through regulation and licensing, and raised $16 billion to expand the autonomous service.",
        tags=("automation",),
        source_id="business_insider_feed",
        source_name="Business Insider Feed",
        source_url="https://business-insider.example/medium-waymo.xml",
        source_priority=100,
        item_link="https://www.businessinsider.com/waymo",
        claude_result=ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title="Edited Waymo title",
            edited_summary="Edited summary suggesting the story might be worth sending.",
            confidence="medium",
            used_claude=True,
        ),
    )
    assert baseline_result.sent_items == 0
    assert result.sent_items == 0
    assert len(sent_cards) == 0
    assert signals["claude_editorial_reviewed"] is False
    assert signals["claude_editorial_outcome"] == "not_reviewed"
    assert signals["claude_editorial_not_reviewed_reason"] == "ineligible"
    assert signals.get("claude_editorial_medium_promoted") is not True
    assert send_status == "skip"
    assert skip_reason in {"no_clear_all3_scope", "obvious_off_scope"}

def test_claude_editorial_medium_promotion_requires_send_ok_complete_edits_and_medium_confidence(
    monkeypatch, tmp_path
) -> None:
    cases = [
        ClaudeEditorialReviewResult(
            send_ok=False,
            reject_reason="borderline_not_strong_enough",
            edited_title=None,
            edited_summary=None,
            confidence="medium",
            used_claude=True,
        ),
        ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title=None,
            edited_summary="Usable summary but missing title.",
            confidence="medium",
            used_claude=True,
        ),
        ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title="Usable title but missing summary",
            edited_summary=None,
            confidence="medium",
            used_claude=True,
        ),
        ClaudeEditorialReviewResult(
            send_ok=True,
            reject_reason=None,
            edited_title="Low confidence title",
            edited_summary="Low confidence summary",
            confidence="low",
            used_claude=True,
        ),
    ]

    for index, claude_result in enumerate(cases, start=1):
        baseline_result, result, sent_cards, send_status, skip_reason, signals = _run_claude_editorial_single_case(
            monkeypatch,
            tmp_path,
            slug=f"medium-guard-{index}",
            title="Robotics segment revenue rises at the start of 2026",
            description="Teradyne Robotics brought in $91 million in Q1 2026, with its AI products helping to boost robotics sales.",
            tags=("robotics", "industrial"),
            claude_result=claude_result,
        )
        assert signals.get("claude_editorial_medium_promoted") is not True
        assert signals["claude_editorial_outcome"] == "fallback_low_or_medium_confidence"
        assert signals["claude_editorial_confidence"] == claude_result.confidence
        assert baseline_result.sent_items == result.sent_items
        assert len(sent_cards) == result.sent_items
        assert send_status in {"stored_only", "sent", "skip"}
        assert skip_reason in {None, "editorial_not_telegram_worthy", "already_sent_canonical_event", "telegram_send_failed"}


def test_claude_editorial_review_pool_prioritizes_strategic_borderline_candidates(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_editorial_priority.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_EDITORIAL_MAX_CANDIDATES", "6")
    monkeypatch.setenv("CLAUDE_FINAL_CARD_ENABLED", "false")

    now = datetime.now(timezone.utc)

    def item_xml(title: str, link: str, description: str, guid: str) -> str:
        return f"""
  <item>
    <title>{title}</title>
    <link>{link}</link>
    <description>{description}</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>{guid}</guid>
  </item>"""

    feeds = {
        "https://business-insider.example/feed.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>{
            item_xml(
                "Waymo, Alphabet's robotaxi service, is growing fast. Here's how to ride, costs, and the self-driving cars' crash record.",
                "https://www.businessinsider.com/waymo",
                "Waymo is Alphabet's robotaxi service. It has partnered with Uber and DoorDash, launched public rides across cities, worked through regulation and licensing, and raised $16 billion to expand the autonomous service.",
                "bi-waymo",
            )
        }
</channel></rss>""",
        "https://wood-central.example/feed.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>{
            item_xml(
                "American Loggers Helped Write Trump’s Lumber Order. Now It Wants New Markets to Match",
                "https://woodcentral.com.au/american-loggers-helped-write-trump-lumber-order/",
                "The timber policy and lobbying story focuses on the executive order, regulation, and trade positioning rather than automation or industrial operations.",
                "wood-loggers",
            )
        }
</channel></rss>""",
        "https://ai-insider.example/feed.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>{
            item_xml(
                "China Warehouse Robotics Company HyperLeap Enters US Market",
                "https://theaiinsider.tech/2026/04/30/china-warehouse-robotics-company-hyperleap-enters-us-market/",
                "The warehouse robotics company is entering the US market with fulfillment automation and sorting systems.",
                "ai-hyperleap",
            )
        }
</channel></rss>""",
        "https://robot-report.example/feed.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>{
                item_xml(
                    "Robotics segment revenue rises at the start of 2026",
                    "https://www.therobotreport.com/teradyne-robotics-revenue-rises-start-2026/",
                    "Teradyne Robotics brought in $91 million in Q1 2026, with its AI products helping to boost robotics sales.",
                    "rr-teradyne",
                )
            }{
                item_xml(
                    "Manufacturing language model speeds industrial automation design",
                    "https://www.therobotreport.com/launchpad-build-ai-offers-manufacturing-language-model-industrial-automation/",
                    "Launchpad Build AI says its Manufacturing Language Model can democratize automation for high-mix, low-volume production with inputs from photos, videos, or CAD.",
                    "rr-launchpad",
                )
            }</channel></rss>""",
        "https://robotics-automation.example/feed.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>{
            item_xml(
                "Surplus robots, robot welders, and support equipment to be auctioned by BTM Industrial",
                "https://roboticsandautomationnews.com/2026/04/30/surplus-robots-robot-welders-and-support-equipment-to-be-auctioned-by-btm-industrial/101124/",
                "BTM Industrial is liquidating surplus inventory and auctioning robot welders and support equipment to free up floor space.",
                "ran-auction",
            )
        }{
            item_xml(
                "How Access Control Systems Integrate with Industrial IoT for Real-Time Security Automation",
                "https://roboticsandautomationnews.com/2026/04/30/how-access-control-systems-integrate-with-industrial-iot-for-real-time-security-automation/101137/",
                "Factories and logistics hubs are using connected sensors and access control systems for real-time security automation in industrial IoT environments.",
                "ran-access",
            )
        }{
            item_xml(
                "How Procurement Automation Creates Audit-Ready Supply Chains in Manufacturing",
                "https://roboticsandautomationnews.com/2026/04/30/how-procurement-automation-creates-audit-ready-supply-chains-in-manufacturing/101130/",
                "A tier-two automotive supplier used procurement automation to improve approval history and audit-ready supply chain workflows.",
                "ran-procurement",
            )
        }{
                item_xml(
                    "Omni-directional trolley positions greenhouse automation for harvesting robots",
                    "https://roboticsandautomationnews.com/2026/04/30/eternal-ag-launches-omni-directional-trolley-as-stepping-stone-to-fully-automated-greenhouses/101115/",
                    "The German agritech startup calls the trolley a robot-ready stepping stone to greenhouse automation, fully-automated greenhouses, and harvesting robots for industrial greenhouse operations.",
                    "ran-eternal",
                )
            }</channel></rss>""",
        "https://tech-funding.example/feed.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>{
                item_xml(
                    "Robotics-led infrastructure venture targets data center buildout",
                    "https://techfundingnews.com/masayoshi-son-softbank-roze-ai-100bn-ipo/",
                    "SoftBank is getting ready to launch Roze AI, a robotics-led infrastructure company combining robotics, data center construction, and physical AI platform ambitions.",
                    "tfn-roze",
                )
            }</channel></rss>""",
    }

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="business_insider_feed",
                name="Business Insider Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://business-insider.example/feed.xml",
                priority=100,
                tags=("automation",),
            ),
            SourceDefinition(
                id="wood_central_api",
                name="Wood Central API",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://wood-central.example/feed.xml",
                priority=95,
                tags=("timber",),
            ),
            SourceDefinition(
                id="ai_insider_rss",
                name="AI Insider RSS",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://ai-insider.example/feed.xml",
                priority=90,
                tags=("robotics",),
            ),
            SourceDefinition(
                id="robot_report_rss",
                name="The Robot Report RSS",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://robot-report.example/feed.xml",
                priority=85,
                tags=("robotics", "industrial"),
            ),
            SourceDefinition(
                id="robotics_automation_news_rss",
                name="Robotics and Automation News RSS",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://robotics-automation.example/feed.xml",
                priority=80,
                tags=("automation",),
            ),
            SourceDefinition(
                id="tech_funding_news_rss",
                name="Tech Funding News RSS",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://tech-funding.example/feed.xml",
                priority=75,
                tags=("funding",),
            ),
        )
    )

    class FakeGeminiClient:
        is_available = False

    class RecordingClaudeEditorialClient:
        is_available = True

        def __init__(self) -> None:
            self.reviewed_titles: list[str] = []

        def review_candidate(self, **kwargs):
            title = kwargs["title"]
            self.reviewed_titles.append(title)
            if title in {
                "Robotics segment revenue rises at the start of 2026",
                "Manufacturing language model speeds industrial automation design",
            }:
                return ClaudeEditorialReviewResult(
                    send_ok=True,
                    reject_reason=None,
                    edited_title=None,
                    edited_summary=None,
                    confidence="medium",
                    used_claude=True,
                )
            return ClaudeEditorialReviewResult(
                send_ok=False,
                reject_reason="not_strategic_enough",
                edited_title=None,
                edited_summary=None,
                confidence="high",
                used_claude=True,
            )

    class FakeTelegramSender:
        def __init__(self) -> None:
            self.sent_cards = []

        def send_card(self, card):
            self.sent_cards.append(card)
            return []

    def fake_fetch_text(url: str) -> str:
        return feeds[url]

    fake_claude = RecordingClaudeEditorialClient()
    fake_sender = FakeTelegramSender()
    captured_stage_counters: dict[str, int] = {}

    def fake_write_run_audit_report(*args, **kwargs):
        nonlocal captured_stage_counters
        captured_stage_counters = dict(args[6])
        return tmp_path / "audit.md"

    monkeypatch.setattr("all3_radar.pipeline.radar_service.write_run_audit_report", fake_write_run_audit_report)

    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=fake_claude,
        telegram_sender=fake_sender,
    )
    result = service.run(dry_run=False)

    assert result.sent_items == 0
    assert len(fake_sender.sent_cards) == 0
    assert captured_stage_counters["claude_editorial_attempted"] == 6
    assert captured_stage_counters["claude_editorial_rejected"] == 4
    assert captured_stage_counters["claude_editorial_fallback"] == 2
    assert captured_stage_counters["claude_editorial_fallback_low_or_medium_confidence"] == 2

    assert {
        "Robotics segment revenue rises at the start of 2026",
        "Manufacturing language model speeds industrial automation design",
        "Robotics-led infrastructure venture targets data center buildout",
        "Omni-directional trolley positions greenhouse automation for harvesting robots",
    } == set(fake_claude.reviewed_titles[:4])
    assert "China Warehouse Robotics Company HyperLeap Enters US Market" not in fake_claude.reviewed_titles
    assert "How Procurement Automation Creates Audit-Ready Supply Chains in Manufacturing" not in fake_claude.reviewed_titles
    assert "How Access Control Systems Integrate with Industrial IoT for Real-Time Security Automation" not in fake_claude.reviewed_titles
    assert "Waymo, Alphabet's robotaxi service, is growing fast. Here's how to ride, costs, and the self-driving cars' crash record." not in fake_claude.reviewed_titles

    for title in (
        "Robotics segment revenue rises at the start of 2026",
        "Manufacturing language model speeds industrial automation design",
        "Robotics-led infrastructure venture targets data center buildout",
        "Omni-directional trolley positions greenhouse automation for harvesting robots",
    ):
        send_status, skip_reason, signals, _ = _load_radar_decision_for_title(db_path, title)
        assert send_status == "stored_only"
        assert skip_reason in {None, "editorial_not_telegram_worthy", "claude_editorial_rejected"}


def test_claude_editorial_ineligible_candidate_records_not_reviewed_reason(
    monkeypatch, tmp_path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "radar_claude_editorial_ineligible.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_EDITORIAL_ENABLED", "true")

    now = datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Kewazo raises funding for construction robot rollout</title>
    <link>https://example.com/kewazo</link>
    <description>The company said the round will support factory and jobsite deployment expansion.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>a1</guid>
  </item>
  <item>
    <title>Apptronik expands leadership team with new executive hires</title>
    <link>https://example.com/apptronik-hires</link>
    <description>The company appointed new executives and expanded the leadership team.</description>
    <pubDate>{format_datetime(now - timedelta(hours=1))}</pubDate>
    <guid>b1</guid>
  </item>
</channel></rss>"""

    registry = SourceRegistry(
        (
            SourceDefinition(
                id="claude_editorial_ineligible_feed",
                name="Claude Editorial Ineligible Feed",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://example.com/claude-editorial-ineligible.xml",
                priority=100,
                tags=("robotics",),
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
            return []

    class FakeClaudeEditorialClient:
        is_available = True

        def review_candidate(self, **kwargs):
            return ClaudeEditorialReviewResult(
                send_ok=True,
                reject_reason=None,
                edited_title=None,
                edited_summary=None,
                confidence="medium",
                used_claude=True,
            )

    def fake_fetch_text(url: str) -> str:
        assert url == "https://example.com/claude-editorial-ineligible.xml"
        return feed

    service = RadarService(
        repo_root=repo_root,
        registry=registry,
        fetch_text_fn=fake_fetch_text,
        gemini_client=FakeGeminiClient(),
        claude_editorial_review_client=FakeClaudeEditorialClient(),
        telegram_sender=FakeTelegramSender(),
    )
    service.run(dry_run=False)

    send_status, skip_reason, signals, _ = _load_radar_decision_for_title(
        db_path, "Apptronik expands leadership team with new executive hires"
    )
    assert send_status == "skip"
    assert skip_reason == "no_clear_all3_scope"
    assert signals["claude_editorial_reviewed"] is False
    assert signals["claude_editorial_outcome"] == "not_reviewed"
    assert signals["claude_editorial_not_reviewed_reason"] == "ineligible"
