from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import StoredNormalizedItem
from all3_radar.pipeline.ranking import derive_event_flags
from all3_radar.pipeline.filters import (
    compute_relevance_status,
    is_destatis_construction_statistics_signal,
    is_wood_central_timber_economics_signal,
    is_wood_central_timber_policy_signal,
)


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
        metadata={"tags": ["tech"], "broad_feed": broad_feed},
    )


def test_broad_feed_requires_clear_all3_scope() -> None:
    item = _make_item(
        "Google to invest up to $40B in Anthropic in cash and compute",
        "Generic AI financing story about enterprise software, chat assistants, and office productivity.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_warehouse_story_without_clear_strategic_scope_is_dropped() -> None:
    item = _make_item(
        "Humanoid robots pilot begins in warehouse operations",
        "A warehouse pilot starts for humanoid robots in logistics workflows.",
        broad_feed=False,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_broad_feed_story_with_generic_factory_language_is_dropped() -> None:
    item = _make_item(
        "AI startups are raising millions to disrupt Hollywood",
        "Studios adopt AI for production and marketing as founders share pitch decks to raise funding.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_broad_feed_story_with_generic_automation_language_is_dropped() -> None:
    item = _make_item(
        "MrBeast is plotting a move into AI-native entertainment",
        "The company wants to build a production team around AI automation for content workflows.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_broad_feed_physical_ai_story_with_real_world_robotics_scope_survives() -> None:
    item = _make_item(
        "Neura Robotics and Dassault Systèmes partner to scale physical AI",
        "The companies connect robot training in virtual twins with real-world deployment across physical robot environments.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_focused_robot_programming_story_survives_scope_gate() -> None:
    item = _make_item(
        "Ency updates hybrid robot programming platform with multi-brand and 3D vision capabilities",
        "The update adds support for mixed-brand robot cells and integrated 3D vision with physical robots.",
        broad_feed=False,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_military_robotics_story_is_dropped_by_default() -> None:
    item = _make_item(
        "Ukrainian startup upgrades battlefield robots like smartphones",
        "The company says its battlefield robots can receive regular defense software and combat hardware upgrades.",
        broad_feed=False,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "obvious_off_scope"


def test_general_business_profile_story_is_dropped() -> None:
    item = _make_item(
        "Goldman banker wants to trade his $4.8 million California estate for shares in Anthropic",
        "The banker is offering his luxury estate in exchange for private-company shares in Anthropic.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "obvious_off_scope"


def test_destatis_construction_statistics_signal_is_detected() -> None:
    item = _make_item(
        "Auftragseingang im Bauhauptgewerbe im Februar 2026: +7,3 % zum Vormonat",
        "Der reale Auftragseingang im Bauhauptgewerbe ist im Februar 2026 gegenüber Januar 2026 gestiegen.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "destatis_press_listing"})

    assert is_destatis_construction_statistics_signal(item) is True


def test_wood_central_timber_policy_signal_is_detected() -> None:
    item = _make_item(
        "Architects, insurers open new front on English timber cap",
        "Architects and insurers have raised fresh concerns over England's timber height cap and standards.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "wood_central_api"})

    assert is_wood_central_timber_policy_signal(item) is True


def test_wood_central_timber_economics_signal_is_detected() -> None:
    item = _make_item(
        "Mass timber premiums run six to ten times higher than concrete and steel",
        "A quantified cost comparison suggests mass timber premiums remain a major adoption barrier for commercial viability and timber scaling.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "wood_central_api"})

    assert is_wood_central_timber_economics_signal(item) is True


def test_soft_wood_central_timber_economics_commentary_does_not_trigger_signal() -> None:
    item = _make_item(
        "Why mass timber economics deserve a broader conversation",
        "A commentary on long-term timber costs and market positioning without a quantified comparison or clear adoption-barrier signal.",
        broad_feed=False,
    )
    item = StoredNormalizedItem(**{**item.__dict__, "source_id": "wood_central_api"})

    assert is_wood_central_timber_economics_signal(item) is False


def test_broad_feed_major_industrial_ai_funding_story_survives_scope_gate() -> None:
    item = _make_item(
        "Project Prometheus raises funding at $38B valuation for physics AI",
        "The company says the round will expand AI systems for engineering, manufacturing and production workflows across physical industries.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_bioorbit_style_space_drug_manufacturing_story_is_dropped() -> None:
    item = _make_item(
        "BioOrbit zips £9.8M to make cancer drugs in orbit in the largest-ever in-space manufacturing seed round",
        "The company says the funding will scale in-space drug manufacturing and therapeutic production for cancer medicines.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "obvious_off_scope"


def test_generic_pharma_drug_manufacturing_funding_story_is_dropped() -> None:
    item = _make_item(
        "Biotech startup raises $60M to expand pharmaceutical manufacturing for clinical therapies",
        "The funding will support therapeutic production, clinical manufacturing capacity, and biopharma scale-up.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "obvious_off_scope"


def test_valid_industrial_robotics_funding_story_still_keeps_scope() -> None:
    item = _make_item(
        "Industrial robotics startup raises $120M to expand factory automation deployments",
        "The company says the funding will support robotics systems, robot cells, and automation rollouts across factories.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_valid_construction_automation_story_still_keeps_scope() -> None:
    item = _make_item(
        "Construction automation startup launches robotic system for jobsite material handling",
        "The company says the system will improve worksite productivity and support industrialized construction workflows.",
        broad_feed=False,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_valid_timber_industrialized_construction_story_still_keeps_scope() -> None:
    item = _make_item(
        "Mass timber platform expands modular housing production with factory-built system",
        "The company says the rollout will scale industrialized construction, modular housing delivery, and mass timber production.",
        broad_feed=False,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_broad_feed_major_industrial_ai_merger_story_survives_scope_gate() -> None:
    item = _make_item(
        "Cohere and Aleph Alpha explore merger with Schwarz Group backing",
        "The proposed $20B merger with $600M backing would combine enterprise AI with engineering, industrial automation and manufacturing workflow software for European production environments.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "keep"
    assert reason is None


def test_generic_broad_feed_ai_merger_without_physical_industry_scope_stays_dropped() -> None:
    item = _make_item(
        "Cohere and Aleph Alpha explore merger for enterprise AI expansion",
        "The companies are discussing a strategic AI merger to expand enterprise chat and office productivity tools.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_mrbeast_ai_entertainment_story_no_longer_survives_strategic_ai_scope_gate() -> None:
    item = _make_item(
        "MrBeast is plotting a move into AI-native entertainment",
        "The company wants to build a production team around AI automation for content workflows.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"


def test_hollywood_ai_funding_story_no_longer_survives_strategic_ai_scope_gate() -> None:
    item = _make_item(
        "AI startups are raising millions to disrupt Hollywood",
        "Studios adopt AI for production, marketing, and visual effects as founders raise money to change film and TV workflows.",
        broad_feed=True,
    )

    status, reason = compute_relevance_status(
        item=item,
        competitor_count=0,
        freshness_is_fresh=True,
        event_flags=derive_event_flags(item),
    )

    assert status == "drop"
    assert reason == "no_clear_all3_scope"
