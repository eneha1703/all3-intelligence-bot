from datetime import datetime, timezone

from all3_radar.digest.corpus import DigestCandidate
from all3_radar.digest.writer import build_digest_markdown


def test_build_digest_markdown_includes_deterministic_sections() -> None:
    candidate = DigestCandidate(
        canonical_event_id="event-1",
        normalized_item_id="item-1",
        source_id="robot_report_rss",
        title="Flex and Teradyne expand partnership to scale physical AI",
        canonical_url="https://example.com/flex-teradyne",
        published_ts=datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc),
        score=82,
        summary_text="Flex and Teradyne expanded their partnership to accelerate physical AI in manufacturing.",
        event_flags={"partnership_event": True, "industrial_robotics_signal": True},
    )

    markdown = build_digest_markdown(
        "2026-W18",
        [candidate],
        claude_section="## Claude Synthesis\n- Robotics partnerships clustered around manufacturing execution.\n",
    )

    assert "# Bot 1 Weekly Digest — 2026-W18" in markdown
    assert "## Claude Synthesis" in markdown
    assert "## Signals Snapshot" in markdown
    assert "## Top Stories" in markdown
    assert "[Flex and Teradyne expand partnership to scale physical AI](https://example.com/flex-teradyne)" in markdown
