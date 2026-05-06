import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from all3_radar.delivery.telegram import TelegramDelivery
from all3_radar.domain.enums import FreshnessStatus, PipelineName, SourceKind, SourceLayer
from all3_radar.domain.models import (
    CollectedRawItem,
    FreshnessEvaluation,
    NormalizedItem,
    RankedDecision,
    SourceDefinition,
    SummaryResult,
)
from all3_radar.pipeline import replay_service as replay_module
from all3_radar.pipeline.replay_service import ReplayService
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository


def test_replay_allowlist_sends_only_allowlisted_urls_in_order_without_label(
    monkeypatch, tmp_path, caplog
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "replay_allowlist.db"
    allowlist_path = tmp_path / "allowlist.txt"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    initialize_database(db_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")

    repository = RadarRepository(db_path)
    repository.upsert_sources(
        (
            SourceDefinition(
                id="robotics_automation_news_rss",
                name="Robotics & Automation News",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://roboticsandautomationnews.com/feed/",
                priority=90,
                tags=("robotics",),
            ),
            SourceDefinition(
                id="robot_report_rss",
                name="The Robot Report",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://www.therobotreport.com/feed/",
                priority=90,
                tags=("robotics",),
            ),
            SourceDefinition(
                id="tech_eu_rss",
                name="Tech.eu",
                kind=SourceKind.RSS,
                layer=SourceLayer.DIRECT,
                is_direct_source=True,
                is_wrapper=False,
                enabled=True,
                parser="generic_rss",
                url="https://tech.eu/feed/",
                priority=90,
                tags=("construction", "robotics"),
            ),
        )
    )

    seed_run_id = repository.create_pipeline_run(PipelineName.RADAR, {"seed": True})
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)

    def persist_item(
        *,
        source_id: str,
        url: str,
        title: str,
        preview: str,
        published_hours_ago: int,
        score: int,
    ) -> str:
        raw_id = repository.insert_raw_item(
            seed_run_id,
            CollectedRawItem(
                source_id=source_id,
                url=url,
                title=title,
                snippet=preview,
                author=None,
                published_ts=now - timedelta(hours=published_hours_ago),
                collected_ts=now,
            ),
        )
        normalized_id = repository.insert_normalized_item(
            raw_id,
            NormalizedItem(
                source_id=source_id,
                canonical_url=url,
                domain=url.split("/")[2],
                title=title,
                dek=None,
                text_preview=preview,
                published_ts=now - timedelta(hours=published_hours_ago),
                collected_ts=now,
                language="en",
                layer=SourceLayer.DIRECT,
                is_wrapper=False,
                directness_rank=100,
                metadata={},
            ),
        )
        repository.upsert_radar_decision(
            normalized_item_id=normalized_id,
            canonical_event_id=None,
            freshness=FreshnessEvaluation(FreshnessStatus.FRESH, True, "fresh"),
            relevance_status="keep",
            send_status="stored_only",
            skip_reason=None,
            score=score,
            signals={"construction_signal": True},
            summary_text=None,
            used_gemini=False,
        )
        return normalized_id

    flex_url = "https://roboticsandautomationnews.com/2026/04/24/flex-and-teradyne-robotics-expand-partnership-to-scale-intelligent-automation-across-global-manufacturing/101001/"
    all3_url = "https://tech.eu/2026/04/29/all3-raises-25m-to-boost-construction-productivity-with-robotics-and-ai/"
    missing_url = "https://example.com/missing-story"

    persist_item(
        source_id="robotics_automation_news_rss",
        url=flex_url,
        title="Flex and Teradyne Robotics expand partnership to scale intelligent automation across global manufacturing",
        preview="Flex and Teradyne Robotics expanded their partnership to accelerate intelligent automation across manufacturing sites.",
        published_hours_ago=10,
        score=96,
    )
    persist_item(
        source_id="robotics_automation_news_rss",
        url=flex_url,
        title="Flex and Teradyne broaden automation partnership",
        preview="Flex and Teradyne Robotics are broadening their automation partnership across factories.",
        published_hours_ago=11,
        score=78,
    )
    persist_item(
        source_id="robot_report_rss",
        url="https://www.therobotreport.com/flex-teradyne-partnership-story/",
        title="Flex and Teradyne expand partnership for industrial automation",
        preview="The companies are scaling industrial automation programs together.",
        published_hours_ago=9,
        score=93,
    )
    persist_item(
        source_id="tech_eu_rss",
        url=all3_url,
        title="All3 raises $25M to boost construction productivity with robotics and AI",
        preview="All3 has raised $25 million to expand its robotics platform for construction productivity.",
        published_hours_ago=2,
        score=97,
    )

    allowlist_path.write_text(f"{all3_url}\n{missing_url}\n{flex_url}\n", encoding="utf-8")

    class FakeGeminiClient:
        is_available = False

    class FakeTelegramSender:
        def __init__(self) -> None:
            self.sent_cards = []

        def send_card(self, card):
            self.sent_cards.append(card)
            return [
                TelegramDelivery(
                    chat_id="replay-chat",
                    status="sent",
                    telegram_message_id=f"msg-{len(self.sent_cards)}",
                    error_text=None,
                    payload_text=card.text,
                )
            ]

    fake_sender = FakeTelegramSender()

    monkeypatch.setattr(
        replay_module,
        "summarize_candidate",
        lambda item, decision, gemini_client: SummaryResult(
            summary_text=item.text_preview,
            used_gemini=False,
            gemini_decision_override=None,
        ),
    )
    monkeypatch.setattr(
        replay_module,
        "evaluate_send_stage_editorial",
        lambda item, decision: type("EditorialResult", (), {"allow_send": True, "reason": "eligible"})(),
    )
    monkeypatch.setattr(
        replay_module,
        "rank_item",
        lambda item, competitor_count, freshness_is_fresh, ranking_rules: RankedDecision(
            relevance_status="keep",
            send_status="stored_only",
            skip_reason=None,
            score=97 if item.canonical_url == all3_url else 96 if item.canonical_url == flex_url else 93,
            signals={"manual_replay_test": True},
            is_shortlisted=True,
            is_borderline=False,
        ),
    )

    caplog.set_level("INFO")
    service = ReplayService(
        repo_root=repo_root,
        repository=repository,
        gemini_client=FakeGeminiClient(),
        telegram_sender=fake_sender,
    )
    result = service.replay_window(
        start_date="2026-04-24",
        end_date="2026-04-29",
        replay_label="",
        send=True,
        allowlist_urls_file=allowlist_path,
    )

    assert result.sent_items == 2
    assert result.shortlisted_items == 2
    assert len(fake_sender.sent_cards) == 2
    assert fake_sender.sent_cards[0].url == all3_url
    assert fake_sender.sent_cards[1].url == flex_url
    assert fake_sender.sent_cards[0].text.startswith("<b>All3 raises $25M")
    assert "<i>" not in fake_sender.sent_cards[0].text
    assert all("therobotreport" not in card.url for card in fake_sender.sent_cards)
    assert "Replay allowlist URL missing from DB window: url=https://example.com/missing-story" in caplog.text
    assert "duplicate_rows_collapsed=1" in caplog.text

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT canonical_event_id, status FROM telegram_deliveries WHERE bot_kind = 'replay' ORDER BY created_at"
        ).fetchall()

    assert len(rows) == 2
