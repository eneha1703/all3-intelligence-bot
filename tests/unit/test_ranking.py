from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import StoredNormalizedItem
from all3_radar.pipeline.ranking import rank_item


def _make_item(title: str, preview: str, broad_feed: bool) -> StoredNormalizedItem:
    now = datetime.now(timezone.utc)
    return StoredNormalizedItem(
        normalized_item_id="item-1",
        raw_item_id="raw-1",
        source_id="source-1",
        canonical_url="https://example.com/story",
        domain="example.com",
        title=title,
        text_preview=preview,
        published_ts=now,
        collected_ts=now,
        layer=SourceLayer.DIRECT,
        is_wrapper=False,
        directness_rank=100,
        metadata={"tags": ["robotics"], "broad_feed": broad_feed},
    )


RANKING_RULES = {
    "signals": {
        "competitor_mention": 35,
        "direct_source": 25,
        "google_competitor_wrapper": -30,
        "funding_event": 18,
        "partnership_event": 16,
        "acquisition_event": 20,
        "deployment_event": 20,
        "factory_opening_or_expansion": 18,
        "permitting_or_code_signal": 18,
        "quantified_scale_signal": 15,
        "timber_strategic_signal": 15,
        "industrial_robotics_signal": 8,
        "construction_innovation_signal": 6,
        "consumer_robotics_penalty": -50,
        "showcase_only_architecture_penalty": -20,
    },
    "thresholds": {
        "store_min_score": 0,
        "shortlist_min_score": 20,
        "send_min_score": 28,
    },
}


def test_industrial_physical_ai_story_reaches_send_threshold() -> None:
    item = _make_item(
        "Neura Robotics and Dassault Systèmes partner to scale physical AI",
        "The agreement links robot training in virtual twins with real-world deployment in physical robot environments.",
        broad_feed=True,
    )

    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert decision.relevance_status == "keep"
    assert decision.score >= 28


def test_modular_quantified_construction_story_reaches_send_threshold() -> None:
    item = _make_item(
        "Messer Construction breaks ground on $280M university health building",
        "The 257,000-square-foot facility will feature modular teaching spaces for multiple professions.",
        broad_feed=False,
    )

    decision = rank_item(item=item, competitor_count=0, freshness_is_fresh=True, ranking_rules=RANKING_RULES)

    assert decision.relevance_status == "keep"
    assert decision.score >= 28
