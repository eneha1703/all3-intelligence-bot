import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all3_radar.digest.claude_client import ClaudeDigestUnavailableError
from all3_radar.digest.digest_service import DigestService
from all3_radar.storage.db import initialize_database


ALL3_TITLE_A = "The founders behind a $1.5B food delivery exit just raised $25M from RTP Global for a construction robotics startup"
ALL3_TITLE_B = "UK Robotic Construction Company All3 Raises $25M in Seed Round Funding"
PROMETHEUS_TITLE = "Project Prometheus raises $10B at $38B valuation to build AI for physical industries"
BMW_FUND_TITLE = "BMW’s venture arm just raised a new $300M fund to bet on physical AI and robotics"
BIOORBIT_TITLE = "BioOrbit zips £9.8M to make cancer drugs in orbit in the largest-ever in-space manufacturing seed round"


def _seed_digest_db(db_path: Path, schema_path: Path) -> None:
    initialize_database(db_path, schema_path)
    now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, base_url, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("robot_report_rss", "Robot Report", "rss", "direct", 1, 0, 1, "https://example.com/feed", "{}", now),
        )
        connection.execute(
            """
            INSERT INTO sources (id, name, kind, layer, is_direct_source, is_wrapper, enabled, base_url, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("destatis_press", "Destatis", "listing", "direct", 1, 0, 1, "https://example.com/destatis", "{}", now),
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (id, pipeline, started_at, finished_at, status, config_snapshot_json, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("radar-run-1", "radar", now, now, "completed", "{}", "{}"),
        )

        raw_rows = [
            (
                "raw-1",
                "item-1",
                "event-1",
                "German construction orders recover before capacity does",
                "https://example.com/destatis-orders",
                "destatis_press",
                95,
                "Destatis data showed orders recovering before labor and site capacity normalized.",
                '{"event_flags":{"construction_statistics_signal":true,"construction_innovation_signal":true}}',
            ),
            (
                "raw-2",
                "item-2",
                "event-2",
                "Sereact scales physical AI reliability after fresh funding",
                "https://example.com/sereact",
                "robot_report_rss",
                92,
                "Sereact framed the round around deployment reliability and warehouse production metrics.",
                '{"event_flags":{"funding_event":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-3",
                "item-3",
                "event-3",
                "SoftBank and Roze turn AI infrastructure into a robotics delivery problem",
                "https://example.com/softbank-roze",
                "robot_report_rss",
                89,
                "The story tied data-center construction and physical infrastructure delivery to automation constraints.",
                '{"event_flags":{"funding_event":true,"construction_innovation_signal":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-4",
                "item-4",
                "event-4",
                "Mass timber school pipeline points to repeatable civic deployment",
                "https://example.com/mass-timber",
                "robot_report_rss",
                86,
                "The project mix showed repeatable timber deployment patterns rather than a one-off design feature.",
                '{"event_flags":{"timber_strategic_signal":true}}',
            ),
            (
                "raw-5",
                "item-5",
                "event-5",
                "Flex and Teradyne expand partnership to scale physical AI",
                "https://example.com/flex",
                "robot_report_rss",
                84,
                "Flex and Teradyne expanded manufacturing execution partnerships around physical AI deployment.",
                '{"event_flags":{"partnership_event":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-6",
                "item-6",
                "event-6",
                "Taco Bell adds AI menu personalization",
                "https://example.com/tacobell",
                "robot_report_rss",
                70,
                "The update focused on consumer menu recommendations rather than operational automation.",
                '{"event_flags":{"partnership_event":true}}',
            ),
            (
                "raw-7",
                "item-7",
                "event-7",
                "Waymo, Alphabet's robotaxi service, is growing fast. Here's how to ride, costs, and the self-driving cars' crash record.",
                "https://example.com/waymo-guide",
                "robot_report_rss",
                98,
                "Waymo is Alphabet's robotaxi service, and the story explains where it operates, how to ride it, costs, and the crash record.",
                '{"event_flags":{"deployment_event":true}}',
            ),
            (
                "raw-8",
                "item-8",
                "event-8",
                "2 chefs share how generative AI helps them manage menu changes and event logistics on their own",
                "https://example.com/ai-chefs",
                "robot_report_rss",
                88,
                "Two solo cooking-company operators said AI helps them plan events, research ingredients, and develop social strategy.",
                '{"event_flags":{"partnership_event":true}}',
            ),
            (
                "raw-9",
                "item-9",
                "event-9",
                "Amazon pushes AI use and closely tracks adoption, as some employees push back",
                "https://example.com/amazon-ai-friction",
                "robot_report_rss",
                87,
                "The company is tracking how often engineers use AI tools while facing internal friction and employee pushback.",
                '{"event_flags":{"partnership_event":true}}',
            ),
            (
                "raw-12",
                "item-12",
                "event-12",
                "The founders behind a $1.5B food delivery exit just raised $25M from RTP Global for a construction robotics startup",
                "https://example.com/all3-techfundingnews",
                "robot_report_rss",
                91,
                "All3 has raised $25 million in seed funding from RTP Global to bring its robotic construction platform to market.",
                '{"event_flags":{"funding_event":true,"construction_innovation_signal":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-13",
                "item-13",
                "event-13",
                "UK Robotic Construction Company All3 Raises $25M in Seed Round Funding",
                "https://example.com/all3-aiinsider",
                "robot_report_rss",
                90,
                "UK construction robotics startup All3 has raised $25 million in seed funding led by RTP Global for its autonomous building platform.",
                '{"event_flags":{"funding_event":true,"construction_innovation_signal":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-14",
                "item-14",
                "event-14",
                "Want to hire for your robotics startup? The autonomous vehicle industry is ripe for picking.",
                "https://example.com/robotics-hiring-commentary",
                "robot_report_rss",
                85,
                "Startup CEOs told Business Insider that autonomous-vehicle veterans are a strong talent pool for robotics hiring.",
                '{"event_flags":{"industrial_robotics_signal":true}}',
            ),
            (
                "raw-15",
                "item-15",
                "event-15",
                PROMETHEUS_TITLE,
                "https://example.com/project-prometheus",
                "robot_report_rss",
                90,
                "Project Prometheus raised $10B at a $38B valuation and is building AI systems for aerospace, automotive, advanced manufacturing, and drug discovery.",
                '{"event_flags":{"funding_event":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-16",
                "item-16",
                "event-16",
                BMW_FUND_TITLE,
                "https://example.com/bmw-fund",
                "robot_report_rss",
                89,
                "BMW i Ventures, the independent venture capital arm of BMW Group, has launched its third fund to bet on physical AI and robotics.",
                '{"event_flags":{"funding_event":true,"industrial_robotics_signal":true}}',
            ),
            (
                "raw-17",
                "item-17",
                "event-17",
                BIOORBIT_TITLE,
                "https://example.com/bioorbit",
                "robot_report_rss",
                88,
                "BioOrbit, a London-based in-space drug manufacturing company, has raised £9.8 million in a seed round.",
                '{"event_flags":{"funding_event":true}}',
            ),
        ]
        for raw_id, item_id, event_id, title, url, source_id, score, summary_text, signals_json in raw_rows:
            connection.execute(
                """
                INSERT INTO raw_items (id, run_id, source_id, external_id, url, title, snippet, author, published_ts, collected_ts, raw_payload_json, fetch_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (raw_id, "radar-run-1", source_id, None, url, title, None, None, now, now, "{}", "collected"),
            )
            connection.execute(
                """
                INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    raw_id,
                    source_id,
                    url,
                    "example.com",
                    title,
                    None,
                    f"Preview for {title}",
                    now,
                    now,
                    "de" if source_id == "destatis_press" else "en",
                    "direct",
                    0,
                    100,
                    "{}",
                ),
            )
            connection.execute(
                """
                INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    event_id,
                    "fresh",
                    "keep",
                    "sent" if item_id in {"item-1", "item-2", "item-7", "item-12", "item-15"} else "stored_only",
                    None,
                    score,
                    signals_json,
                    summary_text,
                    0,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, item_id, event_id, title, now, now, now, now),
            )
            connection.execute(
                """
                INSERT INTO event_members (canonical_event_id, normalized_item_id, is_representative)
                VALUES (?, ?, ?)
                """,
                (event_id, item_id, 1),
            )
        connection.commit()


class _FakeClaudeClient:
    is_available = True

    def __init__(self) -> None:
        self.selection_prompts: list[str] = []
        self.writer_prompts: list[str] = []

    def select_top_story_ids(self, prompt: str, *, allowed_ids: set[str], exact_count: int = 5) -> list[str]:
        self.selection_prompts.append(prompt)
        assert exact_count == 5
        selected_ids = ["event-2", "event-4", "event-15", "event-3", "event-12"]
        assert len(selected_ids) == len(set(selected_ids))
        assert set(selected_ids).issubset(allowed_ids)
        return selected_ids

    def generate_telegram_digest(self, prompt: str, *, expected_title: str) -> str:
        self.writer_prompts.append(prompt)
        assert "Sereact scales physical AI reliability after fresh funding" in prompt
        assert PROMETHEUS_TITLE in prompt
        assert "Taco Bell adds AI menu personalization" not in prompt
        assert BMW_FUND_TITLE not in prompt
        assert BIOORBIT_TITLE not in prompt
        return "\n\n".join(
            [
                expected_title,
                '1. <b>Sereact turns funding into a reliability test for warehouse physical AI</b>\n'
                'The funding matters less as capital than as a signal that customers now expect measurable production reliability from warehouse robotics platforms. <a href="https://example.com/sereact">Link</a>',
                '2. <b>Mass timber moves from showcase projects toward repeatable civic deployment</b>\n'
                'The typology mix suggests timber adoption is broadening into replicable public-sector delivery rather than isolated demonstration work. <a href="https://example.com/mass-timber">Link</a>',
                '3. <b>Project Prometheus shows how big the physical AI bet is becoming</b>\n'
                'The round size matters because investors are starting to treat physical AI as a platform opportunity across aerospace, automotive, advanced manufacturing, and drug discovery. <a href="https://example.com/project-prometheus">Link</a>',
                '4. <b>SoftBank and Roze show AI infrastructure becoming a physical automation problem</b>\n'
                'The strategic signal is that data-center growth now depends on construction and delivery automation, not just compute budgets. <a href="https://example.com/softbank-roze">Link</a>',
                '5. <b>All3 raises $25M for robotic construction</b>\n'
                'All3 combines AI-assisted design, off-site robotic fabrication, and on-site assembly into a construction platform tied to real deployment economics. <a href="https://example.com/all3-techfundingnews">Link</a>',
            ]
        )


class _FailingClaudeClient:
    is_available = True

    def select_top_story_ids(self, prompt: str, *, allowed_ids: set[str], exact_count: int = 5) -> list[str]:
        raise ClaudeDigestUnavailableError("timeout")

    def generate_telegram_digest(self, prompt: str, *, expected_title: str) -> str:
        raise ClaudeDigestUnavailableError("timeout")


def test_digest_build_generates_telegram_ready_artifact_with_claude(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "weekly_digest_2026-W18.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "true")

    fake_client = _FakeClaudeClient()
    service = DigestService(repo_root=repo_root, claude_client=fake_client)
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 6
    assert result.claude_used is True
    assert result.fallback_reason is None

    digest_text = output_path.read_text(encoding="utf-8")
    assert digest_text.startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert '<a href="https://example.com/sereact">Link</a>' in digest_text
    assert "https://example.com/sereact" not in digest_text.replace(
        '<a href="https://example.com/sereact">Link</a>', ""
    )
    assert "Taco Bell adds AI menu personalization" not in digest_text
    assert "Waymo, Alphabet's robotaxi service" not in digest_text
    assert "2 chefs share how generative AI helps" not in digest_text
    assert "Amazon pushes AI use and closely tracks adoption" not in digest_text
    assert "Want to hire for your robotics startup" not in digest_text
    assert sum(title in digest_text for title in (ALL3_TITLE_A, ALL3_TITLE_B)) <= 1
    assert "Sereact turns funding into a reliability test" in digest_text
    assert "Project Prometheus shows how big the physical AI bet is becoming" in digest_text
    assert BMW_FUND_TITLE not in digest_text
    assert BIOORBIT_TITLE not in digest_text

    report_path = tmp_path / "weekly_digest_2026-W18.report.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "## Claude Digest Status" in report_text
    assert "- Claude used: yes" in report_text
    assert "- Fallback reason: none" in report_text
    assert "## Top Stories" in report_text
    assert "Sereact scales physical AI reliability after fresh funding" in report_text
    assert PROMETHEUS_TITLE in report_text
    assert "Mass timber school pipeline points to repeatable civic deployment" in report_text
    assert "SoftBank and Roze turn AI infrastructure into a robotics delivery problem" in report_text
    assert "Waymo, Alphabet's robotaxi service" not in report_text
    assert "2 chefs share how generative AI helps" not in report_text
    assert "Amazon pushes AI use and closely tracks adoption" not in report_text
    assert "Want to hire for your robotics startup" not in report_text
    assert sum(title in report_text for title in (ALL3_TITLE_A, ALL3_TITLE_B)) == 1
    assert BMW_FUND_TITLE not in report_text
    assert BIOORBIT_TITLE not in report_text

    assert len(fake_client.selection_prompts) == 1
    assert len(fake_client.writer_prompts) == 1


def test_digest_build_prefers_sent_stories_before_stored_only_backfill(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "weekly_digest_2026-W18.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "false")

    service = DigestService(repo_root=repo_root)
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 6
    assert result.claude_used is False
    report_text = (tmp_path / "weekly_digest_2026-W18.report.md").read_text(encoding="utf-8")
    assert "Sereact scales physical AI reliability after fresh funding" in report_text
    assert "Mass timber school pipeline points to repeatable civic deployment" in report_text
    assert "SoftBank and Roze turn AI infrastructure into a robotics delivery problem" in report_text
    assert ALL3_TITLE_A in report_text
    assert PROMETHEUS_TITLE in report_text
    assert "Waymo, Alphabet's robotaxi service" not in report_text


def test_digest_build_falls_back_to_deterministic_artifact_without_claude(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "weekly_digest_2026-W18.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "true")

    service = DigestService(repo_root=repo_root, claude_client=_FailingClaudeClient())
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 6
    assert result.claude_used is False
    assert result.fallback_reason == "timeout"
    digest_text = output_path.read_text(encoding="utf-8")
    assert digest_text.startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert '<a href="https://example.com/sereact">Link</a>' in digest_text
    assert "Taco Bell adds AI menu personalization" not in digest_text
    assert "Waymo, Alphabet's robotaxi service" not in digest_text
    assert "2 chefs share how generative AI helps" not in digest_text
    assert "Amazon pushes AI use and closely tracks adoption" not in digest_text
    assert "Want to hire for your robotics startup" not in digest_text
    assert sum(title in digest_text for title in (ALL3_TITLE_A, ALL3_TITLE_B)) == 1
    assert PROMETHEUS_TITLE in digest_text
    assert BMW_FUND_TITLE not in digest_text
    assert BIOORBIT_TITLE not in digest_text

    with sqlite3.connect(db_path) as connection:
        digest_row = connection.execute(
            "SELECT status, final_digest_markdown FROM weekly_digest_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        candidate_count = connection.execute("SELECT COUNT(*) FROM weekly_digest_candidates").fetchone()[0]

    assert digest_row[0] == "completed"
    assert digest_row[1].startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert candidate_count == 6
    report_text = (tmp_path / "weekly_digest_2026-W18.report.md").read_text(encoding="utf-8")
    assert "## Claude Digest Status" in report_text
    assert "- Claude used: no" in report_text
    assert "- Fallback reason: timeout" in report_text


def test_digest_build_dedupes_duplicate_story_candidates(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "digest.db"
    output_path = tmp_path / "weekly_digest_2026-W18.md"
    schema_path = repo_root / "src" / "all3_radar" / "storage" / "schema.sql"
    _seed_digest_db(db_path, schema_path)
    now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).isoformat()

    with sqlite3.connect(db_path) as connection:
        duplicate_rows = [
            ("raw-10", "item-10", "event-10"),
            ("raw-11", "item-11", "event-11"),
        ]
        for raw_id, item_id, event_id in duplicate_rows:
            connection.execute(
                """
                INSERT INTO raw_items (id, run_id, source_id, external_id, url, title, snippet, author, published_ts, collected_ts, raw_payload_json, fetch_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    "radar-run-1",
                    "robot_report_rss",
                    None,
                    "https://example.com/trade-estate-anthropic",
                    "A banker wants to trade his $4.8 million California estate for shares in Anthropic. He's already gotten offers.",
                    None,
                    None,
                    now,
                    now,
                    "{}",
                    "collected",
                ),
            )
            connection.execute(
                """
                INSERT INTO normalized_items (id, raw_item_id, source_id, canonical_url, domain, title, dek, text_preview, published_ts, collected_ts, language, layer, is_wrapper, directness_rank, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    raw_id,
                    "robot_report_rss",
                    "https://example.com/trade-estate-anthropic",
                    "example.com",
                    "A banker wants to trade his $4.8 million California estate for shares in Anthropic. He's already gotten offers.",
                    None,
                    "Duplicate estate-for-shares profile story.",
                    now,
                    now,
                    "en",
                    "direct",
                    0,
                    100,
                    "{}",
                ),
            )
            connection.execute(
                """
                INSERT INTO radar_decisions (normalized_item_id, canonical_event_id, freshness_status, relevance_status, send_status, skip_reason, score, signals_json, summary_text, used_gemini, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    event_id,
                    "fresh",
                    "keep",
                    "stored_only",
                    None,
                    81,
                    '{"event_flags":{"funding_event":true}}',
                    "The banker says he has received multiple offers from employees since posting the deal this week.",
                    0,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO canonical_events (id, representative_item_id, event_key, cluster_title, first_published_ts, last_published_ts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    item_id,
                    event_id,
                    "A banker wants to trade his $4.8 million California estate for shares in Anthropic. He's already gotten offers.",
                    now,
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO event_members (canonical_event_id, normalized_item_id, is_representative)
                VALUES (?, ?, ?)
                """,
                (event_id, item_id, 1),
            )
        connection.commit()

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("CLAUDE_DIGEST_ENABLED", "false")

    service = DigestService(repo_root=repo_root)
    result = service.build_digest("2026-W18", output_path=output_path)

    assert result.candidate_count == 6
    digest_text = output_path.read_text(encoding="utf-8")
    assert digest_text.count("A banker wants to trade his $4.8 million California estate for shares in Anthropic") <= 1
    assert digest_text.count("1. <b>") == 1
    assert digest_text.count("<b>") == 5

    report_text = (tmp_path / "weekly_digest_2026-W18.report.md").read_text(encoding="utf-8")
    assert report_text.count("[A banker wants to trade his $4.8 million California estate for shares in Anthropic. He's already gotten offers.]") <= 1
