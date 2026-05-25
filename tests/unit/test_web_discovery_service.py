from datetime import datetime, timezone
from pathlib import Path

from all3_radar.discovery.models import (
    DiscoveryCandidate,
    DiscoveryClientResult,
    DiscoveryConfig,
    DiscoveryQueryPack,
    DiscoveryRuntimeConfig,
)
from all3_radar.discovery.service import WebDiscoveryService
from all3_radar.domain.enums import PipelineName, SourceKind, SourceLayer
from all3_radar.domain.models import CollectedRawItem, NormalizedItem, SourceDefinition
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository


class _FakeDiscoveryClient:
    def discover(self, *, query_packs: tuple, freshness_days: int) -> DiscoveryClientResult:
        return DiscoveryClientResult(
            candidates=(
                DiscoveryCandidate(
                    title="Already seen robotics story",
                    url="https://example.com/seen?utm_source=newsletter",
                    source_name="Example",
                    published_date="2026-05-25",
                    summary="Already in the bot DB.",
                    query_pack_id="test_pack",
                    matched_signal="deployment",
                    why_relevant="Duplicate should be skipped.",
                    confidence="high",
                ),
                DiscoveryCandidate(
                    title="New construction robot deployment",
                    url="https://example.com/new-robot",
                    source_name="Example",
                    published_date="2026-05-25",
                    summary="New deployment on live construction sites.",
                    query_pack_id="test_pack",
                    matched_signal="active deployment",
                    why_relevant="Concrete construction automation signal.",
                    confidence="medium",
                ),
                DiscoveryCandidate(
                    title="Borderline low-confidence item",
                    url="https://example.com/low-confidence",
                    source_name="Example",
                    published_date="2026-05-25",
                    summary="Weakly related item.",
                    query_pack_id="test_pack",
                    matched_signal=None,
                    why_relevant=None,
                    confidence="low",
                ),
            ),
            raw_response_text='{"candidates":[]}',
            web_search_requests=3,
            usage={"server_tool_use": {"web_search_requests": 3}},
        )


def _config() -> DiscoveryConfig:
    return DiscoveryConfig(
        enabled=True,
        provider="claude_web_search",
        freshness_days=3,
        max_search_uses=8,
        max_candidates_returned=20,
        max_new_candidates=12,
        query_packs=(
            DiscoveryQueryPack(
                id="test_pack",
                name="Test pack",
                goal="Find test stories.",
                include_signals=("deployment",),
                exclude_signals=("fluff",),
                queries=("test query",),
            ),
        ),
    )


def _runtime() -> DiscoveryRuntimeConfig:
    return DiscoveryRuntimeConfig(
        api_key="test",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=1000,
        max_search_uses=8,
        max_candidates_returned=20,
        max_new_candidates=12,
    )


def test_web_discovery_service_dedupes_against_bot_history_and_writes_reports(tmp_path) -> None:
    repo_root = tmp_path
    db_path = repo_root / "data" / "test.db"
    schema_path = Path(__file__).resolve().parents[2] / "src" / "all3_radar" / "storage" / "schema.sql"
    initialize_database(db_path, schema_path)
    repository = RadarRepository(db_path)
    source = SourceDefinition(
        id="test_source",
        name="Test Source",
        kind=SourceKind.RSS,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="generic_rss",
        url="https://example.com/feed",
        priority=50,
    )
    repository.upsert_sources((source,))
    run_id = repository.create_pipeline_run(PipelineName.RADAR, {})
    now = datetime.now(timezone.utc)
    raw_id = repository.insert_raw_item(
        run_id,
        CollectedRawItem(
            source_id="test_source",
            url="https://example.com/seen?utm_source=old",
            title="Already seen robotics story",
            snippet="Already in the bot DB.",
            author=None,
            published_ts=now,
            collected_ts=now,
        ),
    )
    repository.insert_normalized_item(
        raw_id,
        NormalizedItem(
            source_id="test_source",
            canonical_url="https://example.com/seen",
            domain="example.com",
            title="Already seen robotics story",
            dek=None,
            text_preview="Already in the bot DB.",
            published_ts=now,
            collected_ts=now,
            language="en",
            layer=SourceLayer.DIRECT,
            is_wrapper=False,
            directness_rank=100,
        ),
    )

    result = WebDiscoveryService(
        repository=repository,
        discovery_config=_config(),
        runtime_config=_runtime(),
        client=_FakeDiscoveryClient(),
    ).run(output_dir=tmp_path / "reports")

    assert result.web_search_requests == 3
    assert len(result.evaluated_candidates) == 3
    assert [item.candidate.title for item in result.accepted_candidates] == ["New construction robot deployment"]
    seen_candidate = result.evaluated_candidates[0]
    assert seen_candidate.dedupe.seen is True
    assert seen_candidate.dedupe.reason == "already_seen_in_bot_history"
    assert seen_candidate.dedupe.match is not None
    assert seen_candidate.dedupe.match.table_name == "normalized_items"
    assert result.report_markdown_path is not None
    assert result.report_json_path is not None
    report_text = Path(result.report_markdown_path).read_text(encoding="utf-8")
    assert "Daily Web Discovery Report" in report_text
    assert "New construction robot deployment" in report_text
    assert "Already seen robotics story" in report_text
