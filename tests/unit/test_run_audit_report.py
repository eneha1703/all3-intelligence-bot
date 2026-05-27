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
            "summary_text": "Story A final summary.",
            "signals_json": (
                '{"card_writer":"claude_final_card",'
                '"final_card_summary_source":"claude_final_card",'
                '"claude_final_card_outcome":"rewritten",'
                '"claude_final_card_reason":null}'
            ),
        },
        {
            "title": "Story B",
            "source_id": "source-b",
            "canonical_url": "https://example.com/b",
            "send_status": "sent",
            "skip_reason": None,
            "summary_text": "Story B fallback summary.",
            "signals_json": (
                '{"card_writer":"deterministic_after_claude_final_card_fallback",'
                '"final_card_summary_source":"gemini_summary",'
                '"claude_final_card_outcome":"fallback_unavailable",'
                '"claude_final_card_reason":"timeout"}'
            ),
        },
        {
            "title": "Suppressed funding duplicate",
            "source_id": "source-c",
            "canonical_url": "https://example.com/c",
            "score": 64,
            "send_status": "skip",
            "skip_reason": "already_sent_same_funding_event",
            "summary_text": "",
            "signals_json": "{}",
        },
        {
            "title": "Suppressed product duplicate",
            "source_id": "source-d",
            "canonical_url": "https://example.com/d",
            "send_status": "skip",
            "skip_reason": "duplicate_same_product_launch_event_shortlist",
            "summary_text": "",
            "signals_json": "{}",
        },
        {
            "title": "Weak card",
            "source_id": "source-e",
            "canonical_url": "https://example.com/e",
            "score": 58,
            "send_status": "skip",
            "skip_reason": "weak_or_empty_telegram_card",
            "summary_text": "",
            "signals_json": "{}",
        },
        {
            "title": "Wohnungsbau-Statistik: Negativrekord bei Fertigstellungen",
            "source_id": "haufe_immobilien_listing",
            "canonical_url": "https://example.com/haufe",
            "score": 57,
            "send_status": "stored_only",
            "skip_reason": "claude_editorial_rejected",
            "summary_text": "",
            "signals_json": (
                '{"claude_editorial_reviewed":true,'
                '"claude_editorial_outcome":"rejected",'
                '"claude_editorial_confidence":"high",'
                '"claude_editorial_reason":"too_thin",'
                '"event_flags":{"housing_market_signal":true}}'
            ),
        },
    ]
    source_audit_rows = [
        {
            "source_id": "source-a",
            "source_name": "Source A",
            "status": "ok",
            "items_collected": 4,
            "duration_seconds": 1.234,
        },
        {
            "source_id": "source-f",
            "source_name": "Source F",
            "status": "failed: timeout",
            "items_collected": 0,
            "duration_seconds": 9.876,
        },
    ]
    stage_timings = {
        "normalization_and_freshness": 12.345,
        "historical_competitor_count_load": 98.765,
    }
    stage_counters = {
        "historical_items_loaded": 321,
        "contexts_count": 20,
        "shortlisted_count": 6,
    }

    markdown = render_run_audit_markdown(
        result,
        decision_rows,
        source_audit_rows,
        123.456,
        stage_timings,
        stage_counters,
    )

    assert "# News Radar Run Audit" in markdown
    assert "- pipeline_run_id: `run-1`" in markdown
    assert "- commit_sha: `abc123`" in markdown
    assert "- db_artifact_reference: `radar-db-999`" in markdown
    assert "- collected: `25`" in markdown
    assert "- send_skips: `3`" in markdown
    assert "- failed_sources: `1`" in markdown
    assert "- duration_seconds: `123.456`" in markdown
    assert "| historical_items_loaded | 321 |" in markdown
    assert "| contexts_count | 20 |" in markdown
    assert "| normalization_and_freshness | 12.345 |" in markdown
    assert "| historical_competitor_count_load | 98.765 |" in markdown
    assert "- `already_sent_same_funding_event`: `1`" in markdown
    assert "- `already_sent_same_deployment_event`: `0`" in markdown
    assert "- `duplicate_same_product_launch_event_shortlist`: `1`" in markdown
    assert "- `duplicate_same_partnership_event_shortlist`: `0`" in markdown
    assert "- `weak_or_empty_telegram_card`: `1`" in markdown
    assert "| Story A | source-a | claude_final_card | claude_final_card | rewritten |  | https://example.com/a |" in markdown
    assert (
        "| Story B | source-b | deterministic_after_claude_final_card_fallback | gemini_summary | "
        "fallback_unavailable | timeout | https://example.com/b |"
    ) in markdown
    assert "| Story A | Story A final summary. |" in markdown
    assert "| Story B | Story B fallback summary. |" in markdown
    assert "## Claude Editorial Reviewed Items" in markdown
    assert (
        "| Wohnungsbau-Statistik: Negativrekord bei Fertigstellungen | haufe_immobilien_listing | "
        "57 | stored_only | claude_editorial_rejected | rejected | high | too_thin | housing_market_signal | "
        "https://example.com/haufe |"
    ) in markdown
    assert "## Top Non-Sent Decisions" in markdown
    assert "| Weak card | source-e | 58 | skip | weak_or_empty_telegram_card |" in markdown
    assert "## Key Source Decisions" in markdown
    assert "| source-f | Source F | failed: timeout | 0 | 9.876 |" in markdown
    assert "| source-a | 4 | 1.234 |" in markdown
    assert "| source-f | 0 | 9.876 |" in markdown


def test_render_run_audit_markdown_uses_gitlab_commit_and_job_reference(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setenv("CI_COMMIT_SHA", "gitlab-sha")
    monkeypatch.setenv("CI_PIPELINE_ID", "123")
    monkeypatch.setenv("CI_JOB_ID", "456")
    result = RadarRunResult(
        run_id="run-2",
        selected_sources=1,
        collected_items=0,
        normalized_items=0,
        fresh_items=0,
        stale_items=0,
        missing_published_ts=0,
        unsupported_sources=0,
        canonical_events=0,
        shortlisted_items=0,
        sent_items=0,
        skipped_send_items=0,
        failed_sources=0,
    )

    markdown = render_run_audit_markdown(result, [])

    assert "- commit_sha: `gitlab-sha`" in markdown
    assert "- db_artifact_reference: `gitlab-pipeline-123-job-456`" in markdown
