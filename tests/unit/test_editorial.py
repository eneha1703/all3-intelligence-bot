from datetime import datetime, timezone

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem
from all3_radar.domain.enums import SourceLayer
from all3_radar.pipeline.editorial import evaluate_send_stage_editorial


def _make_item(title: str, preview: str) -> StoredNormalizedItem:
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
        metadata={},
    )


def _make_decision(**event_flags: bool) -> RankedDecision:
    return RankedDecision(
        relevance_status="keep",
        send_status="stored_only",
        skip_reason=None,
        score=40,
        signals={"competitor_count": 0, "event_flags": event_flags},
        is_shortlisted=True,
        is_borderline=False,
    )


def test_editorial_shaping_rejects_thought_leadership_without_operational_signal() -> None:
    item = _make_item(
        "From sci-fi to reality: Physical AI’s future with Dr. Jan Liphardt",
        "Dr. Jan Liphardt discusses the future of robotics and safety in human-robot interactions.",
    )
    decision = _make_decision()

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_thought_leadership_without_operational_signal"


def test_editorial_shaping_keeps_operational_product_launch() -> None:
    item = _make_item(
        "Ency updates hybrid robot programming platform with multi-brand and 3D vision capabilities",
        "The update adds support for mixed-brand robot cells, SCARA robots, and integrated 3D vision on physical robots.",
    )
    decision = _make_decision(industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is True
    assert editorial.reason is None


def test_editorial_shaping_rejects_adjacent_logistics_without_all3_signal() -> None:
    item = _make_item(
        "Warehouse robotics pilot expands in logistics hubs",
        "The deployment adds AMR routes across warehouse operations and material handling sites.",
    )
    decision = _make_decision(deployment_event=True, adjacent_logistics_only=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_adjacent_logistics_without_all3_signal"


def test_editorial_shaping_rejects_military_robotics() -> None:
    item = _make_item(
        "Defense startup deploys battlefield robots for frontline missions",
        "The military robotics platform will support combat operations and defense logistics on the battlefield.",
    )
    decision = _make_decision(deployment_event=True, industrial_robotics_signal=True)

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_military_or_combat_out_of_scope"


def test_editorial_shaping_rejects_business_profile_noise() -> None:
    item = _make_item(
        "Billionaire banker lists luxury estate while seeking private AI shares",
        "The banker is marketing a luxury estate as part of a personal wealth trade tied to private-company shares.",
    )
    decision = _make_decision()

    editorial = evaluate_send_stage_editorial(item, decision)

    assert editorial.allow_send is False
    assert editorial.reason == "editorial_business_profile_out_of_scope"
