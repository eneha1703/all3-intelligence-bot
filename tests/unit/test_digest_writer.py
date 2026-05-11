from datetime import datetime, timezone

from all3_radar.digest.corpus import DigestCandidate
from all3_radar.digest.writer import build_digest_html, build_digest_markdown


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
        claude_used=True,
        fallback_reason=None,
    )

    assert "# Bot 1 Weekly Digest — 2026-W18" in markdown
    assert "## Claude Synthesis" in markdown
    assert "## Claude Digest Status" in markdown
    assert "- Claude used: yes" in markdown
    assert "- Fallback reason: none" in markdown
    assert "## Signals Snapshot" in markdown
    assert "## Top Stories" in markdown
    assert "[Flex and Teradyne expand partnership to scale physical AI](https://example.com/flex-teradyne)" in markdown


def test_build_digest_html_embeds_link_without_visible_raw_url() -> None:
    candidate = DigestCandidate(
        canonical_event_id="event-1",
        normalized_item_id="item-1",
        source_id="destatis_press",
        title="German construction orders recover before capacity does",
        canonical_url="https://example.com/destatis",
        published_ts=datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc),
        score=82,
        summary_text="Destatis signaled improving order intake while site capacity and labor remain constrained.",
        event_flags={"construction_statistics_signal": True},
    )

    digest_html = build_digest_html(
        "Top 5 News Highlights | 23-30 April 2026 | Week 18",
        [candidate],
    )

    assert digest_html.startswith("Top 5 News Highlights | 23-30 April 2026 | Week 18")
    assert '<a href="https://example.com/destatis">Link</a>' in digest_html
    assert "https://example.com/destatis" not in digest_html.replace('<a href="https://example.com/destatis">Link</a>', "")


def test_build_digest_html_trims_broken_summary_fragments() -> None:
    candidate = DigestCandidate(
        canonical_event_id="event-2",
        normalized_item_id="item-2",
        source_id="ai_insider_rss",
        title="Indian Construction Robotics Startup Flo Mobility Raises $2.5M in Funding",
        canonical_url="https://example.com/flo",
        published_ts=datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc),
        score=86,
        summary_text=(
            "Indian construction robotics startup Flo Mobility announced raising $2.5M in new funding "
            "as the company expands deployment of autonomous material-handling systems across construction "
            "sites in India and international."
        ),
        event_flags={"funding_event": True, "construction_innovation_signal": True},
    )

    digest_html = build_digest_html("Top 5 News Highlights | 7-14 May 2026 | Week 20", [candidate])

    assert "and international." not in digest_html
    assert "construction sites in India." in digest_html


def test_build_digest_html_uses_class_fallback_for_missing_summary() -> None:
    candidate = DigestCandidate(
        canonical_event_id="event-3",
        normalized_item_id="item-3",
        source_id="destatis_press_listing",
        title="11,7 % der Bevölkerung in Deutschland lebten 2025 in überbelegten Wohnungen",
        canonical_url="https://example.com/destatis-overcrowding",
        published_ts=datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc),
        score=51,
        summary_text=None,
        event_flags={"construction_statistics_signal": True},
    )

    digest_html = build_digest_html("Top 5 News Highlights | 7-14 May 2026 | Week 20", [candidate])

    assert "This story remained one of the week's strongest operational signals across the All3 scope." not in digest_html
    assert "Official housing and construction data added another hard market-pressure signal this week." in digest_html
