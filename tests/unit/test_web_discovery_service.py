from datetime import datetime, timezone
from pathlib import Path

from all3_radar.discovery.models import (
    DiscoveryCandidate,
    DiscoveryClientResult,
    DiscoveryConfig,
    DiscoveryQueryPack,
    DiscoveryRuntimeConfig,
)
from all3_radar.discovery.service import WebDiscoveryService, _freshness_rejection_reason
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
                    title="Old construction robot deployment",
                    url="https://example.com/old-robot",
                    source_name="Example",
                    published_date="March 19, 2026",
                    summary="Old deployment item.",
                    query_pack_id="test_pack",
                    matched_signal="active deployment",
                    why_relevant="Relevant but stale.",
                    confidence="high",
                ),
                DiscoveryCandidate(
                    title="Top 10 construction robotics",
                    url="https://example.com/top-10-construction-robotics",
                    source_name="Example",
                    published_date="2026-05-25",
                    summary="Evergreen ranking page.",
                    query_pack_id="test_pack",
                    matched_signal="active deployment",
                    why_relevant="Evergreen page should be skipped.",
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
                DiscoveryCandidate(
                    title="Edge engineering enables physical AI in vehicles",
                    url="https://letsdatascience.com/news/edge-engineering-enables-physical-ai-in-vehicles-2ff1a390",
                    source_name="Let's Data Science",
                    published_date="Mon, 25 May 2026 07:29:24 GMT",
                    summary="Automotive manufacturers are advancing ADAS and in-cabin AI with Tier 1 suppliers.",
                    query_pack_id="industrial_robotics_physical_ai",
                    matched_signal="named industrial customer, plant, site, or partner",
                    why_relevant="Automotive deployment discussion without a plant or factory deployment signal.",
                    confidence="medium",
                ),
                DiscoveryCandidate(
                    title="Physical AI doubles capacity in Tennessee sorting facility",
                    url="https://example.com/sortera-facility",
                    source_name="Robot Report",
                    published_date="Sun, 24 May 2026 12:25:35 GMT",
                    summary="Industrial facility deployment with named site and capacity gain.",
                    query_pack_id="industrial_robotics_physical_ai",
                    matched_signal="factory, warehouse, construction, infrastructure, or industrial deployment",
                    why_relevant="Concrete industrial deployment at a named facility.",
                    confidence="high",
                ),
                DiscoveryCandidate(
                    title="Physical AI doubles capacity at Tennessee sorting facility",
                    url="https://example.com/sortera-facility-duplicate",
                    source_name="Another Outlet",
                    published_date="Sun, 24 May 2026 13:10:00 GMT",
                    summary="Near-duplicate cross-post of the same facility story.",
                    query_pack_id="industrial_robotics_physical_ai",
                    matched_signal="factory, warehouse, construction, infrastructure, or industrial deployment",
                    why_relevant="Same underlying deployment event reported by another outlet.",
                    confidence="medium",
                ),
            ),
            raw_response_text='{"candidates":[]}',
            web_search_requests=3,
            usage={"server_tool_use": {"web_search_requests": 3}},
        )


def _config() -> DiscoveryConfig:
    return DiscoveryConfig(
        enabled=True,
        provider="tavily_search",
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
        search_api_key="search-test",
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
    assert len(result.evaluated_candidates) == 8
    assert [item.candidate.title for item in result.accepted_candidates] == [
        "New construction robot deployment",
        "Physical AI doubles capacity in Tennessee sorting facility",
    ]
    seen_candidate = result.evaluated_candidates[0]
    assert seen_candidate.dedupe.seen is True
    assert seen_candidate.dedupe.reason == "already_seen_in_bot_history"
    assert seen_candidate.dedupe.match is not None
    assert seen_candidate.dedupe.match.table_name == "normalized_items"
    assert result.evaluated_candidates[2].rejection_reason == "outside_freshness_window"
    assert result.evaluated_candidates[3].rejection_reason == "evergreen_or_report_like_content"
    assert result.evaluated_candidates[4].rejection_reason == "low_confidence"
    assert result.evaluated_candidates[5].rejection_reason == "low_signal_source_or_partner_content"
    assert result.evaluated_candidates[7].rejection_reason == "duplicate_in_discovery_response_cluster"
    assert result.report_markdown_path is not None
    assert result.report_json_path is not None
    report_text = Path(result.report_markdown_path).read_text(encoding="utf-8")
    assert "Daily Web Discovery Report" in report_text
    assert "New construction robot deployment" in report_text
    assert "Already seen robotics story" in report_text


def test_freshness_parser_accepts_rfc2822_style_dates() -> None:
    candidate = DiscoveryCandidate(
        title="Fresh Tavily result",
        url="https://example.com/fresh-rfc2822",
        source_name="Example",
        published_date="Mon, 25 May 2026 07:29:24 GMT",
        summary="Fresh result in RSS-style datetime format.",
        query_pack_id="test_pack",
        matched_signal="deployment",
        why_relevant="Fresh and concrete.",
        confidence="high",
    )

    assert (
        _freshness_rejection_reason(
            candidate,
            freshness_days=2,
            now=datetime(2026, 5, 25, 20, 15, 41, tzinfo=timezone.utc),
        )
        is None
    )
