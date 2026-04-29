from all3_radar.domain.models import RadarRunResult
from all3_radar.pipeline.run_audit_report import render_run_audit_markdown


def test_render_run_audit_markdown_includes_summary_skip_counts_and_sent_items(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    result = RadarRunResult(
        run_id="run-1",
        selected_sources=10,
        collected_items=25,
        normalized_items=20,
        fresh_items=18,
        stale_items=2,
        missing_published_ts=1,
        unsupported_sources=0,
        canonical_events=15,
        shortlisted_items=6,
        sent_items=2,
        skipped_send_items=3,
        failed_sources=1,
    )
    decision_rows = [
        {
            "title": "Story A",
            "source_id": "source-a",
            "canonical_url": "https://example.com/a",
            "send_status": "sent",
            "skip_reason": None,
        },
        {
            "title": "Story B",
            "source_id": "source-b",
            "canonical_url": "https://example.com/b",
            "send_status": "sent",
            "skip_reason": None,
        },
        {
            "title": "Suppressed funding duplicate",
            "source_id": "source-c",
            "canonical_url": "https://example.com/c",
            "send_status": "skip",
            "skip_reason": "already_sent_same_funding_event",
        },
        {
            "title": "Suppressed product duplicate",
            "source_id": "source-d",
            "canonical_url": "https://example.com/d",
            "send_status": "skip",
            "skip_reason": "duplicate_same_product_launch_event_shortlist",
        },
        {
            "title": "Weak card",
            "source_id": "source-e",
            "canonical_url": "https://example.com/e",
            "send_status": "skip",
            "skip_reason": "weak_or_empty_telegram_card",
        },
    ]

    markdown = render_run_audit_markdown(result, decision_rows)

    assert "# News Radar Run Audit" in markdown
    assert "- pipeline_run_id: `run-1`" in markdown
    assert "- commit_sha: `abc123`" in markdown
    assert "- db_artifact_reference: `radar-db-999`" in markdown
    assert "- collected: `25`" in markdown
    assert "- send_skips: `3`" in markdown
    assert "- failed_sources: `1`" in markdown
    assert "- `already_sent_same_funding_event`: `1`" in markdown
    assert "- `duplicate_same_product_launch_event_shortlist`: `1`" in markdown
    assert "- `duplicate_same_partnership_event_shortlist`: `0`" in markdown
    assert "- `weak_or_empty_telegram_card`: `1`" in markdown
    assert "| Story A | source-a | https://example.com/a |" in markdown
    assert "| Story B | source-b | https://example.com/b |" in markdown
    assert "- not included yet" in markdown
