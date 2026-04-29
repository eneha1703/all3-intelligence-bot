from datetime import datetime, timedelta, timezone

from all3_radar.pipeline.send_stage_dedupe import (
    SendStageCandidate,
    SuppressedDuplicate,
    suppress_same_event_funding_duplicates,
)


def _candidate(
    item_id: str,
    title: str,
    preview: str,
    score: int = 80,
    published_hours_ago: int = 1,
) -> SendStageCandidate:
    return SendStageCandidate(
        normalized_item_id=item_id,
        canonical_url=f"https://example.com/{item_id}",
        title=title,
        text_preview=preview,
        published_ts=datetime.now(timezone.utc) - timedelta(hours=published_hours_ago),
        score=score,
        event_flags={"funding_event": True},
    )


def test_funding_duplicates_collapse_to_one_representative() -> None:
    left = _candidate(
        "a",
        "The founders behind a $1.5B food delivery exit just raised $25M from RTP Global for a construction robotics startup",
        "All3, a construction robotics company, has raised $25 million in a seed round led by RTP Global.",
        score=88,
    )
    right = _candidate(
        "b",
        "All3 raises $25M to boost construction productivity with robotics and AI",
        "All3 has raised $25 million in a seed round led by RTP Global to scale its robotic construction platform.",
        score=91,
    )

    suppressed = suppress_same_event_funding_duplicates([left, right])

    assert suppressed == [
        SuppressedDuplicate(
            suppressed_item_id="a",
            representative_item_id="b",
            reason="duplicate_same_event_shortlist",
        )
    ]


def test_same_company_different_amount_does_not_collapse() -> None:
    left = _candidate(
        "a",
        "All3 raises $25M to scale construction robotics",
        "All3 has raised $25 million in a seed round led by RTP Global.",
    )
    right = _candidate(
        "b",
        "All3 raises $40M to scale construction robotics",
        "All3 has raised $40 million in a seed round led by RTP Global.",
    )

    assert suppress_same_event_funding_duplicates([left, right]) == []


def test_same_company_different_round_does_not_collapse_without_shared_amount() -> None:
    left = _candidate(
        "a",
        "All3 lands seed financing for construction robotics expansion",
        "All3 has landed a seed round led by RTP Global.",
    )
    right = _candidate(
        "b",
        "All3 secures Series A financing for construction robotics expansion",
        "All3 has secured a Series A round led by RTP Global.",
    )

    assert suppress_same_event_funding_duplicates([left, right]) == []


def test_same_amount_different_companies_do_not_collapse() -> None:
    left = _candidate(
        "a",
        "All3 raises $25M for construction robotics expansion",
        "All3 has raised $25 million in a seed round led by RTP Global.",
    )
    right = _candidate(
        "b",
        "Kewazo raises $25M for construction robotics expansion",
        "Kewazo has raised $25 million in a seed round led by RTP Global.",
    )

    assert suppress_same_event_funding_duplicates([left, right]) == []


def test_generic_profile_does_not_collapse_with_actual_funding_event() -> None:
    profile = SendStageCandidate(
        normalized_item_id="profile",
        canonical_url="https://example.com/profile",
        title="Inside All3's push into construction robotics",
        text_preview="All3 is building robotics systems for construction productivity.",
        published_ts=datetime.now(timezone.utc),
        score=82,
        event_flags={"funding_event": False},
    )
    funding = _candidate(
        "funding",
        "All3 raises $25M to boost construction productivity with robotics and AI",
        "All3 has raised $25 million in a seed round led by RTP Global.",
    )

    assert suppress_same_event_funding_duplicates([profile, funding]) == []


def test_higher_score_wins_for_same_event_duplicates() -> None:
    lower = _candidate(
        "low",
        "All3 raises $25M for robotics rollout",
        "All3 has raised $25 million in a seed round led by RTP Global.",
        score=84,
    )
    higher = _candidate(
        "high",
        "All3 raises $25M to boost construction productivity with robotics and AI",
        "All3 has raised $25 million in a seed round led by RTP Global.",
        score=93,
    )

    suppressed = suppress_same_event_funding_duplicates([lower, higher])

    assert suppressed[0].suppressed_item_id == "low"
    assert suppressed[0].representative_item_id == "high"


def test_richer_direct_event_framing_wins_when_scores_are_close() -> None:
    clickbait = _candidate(
        "clickbait",
        "The founders behind a $1.5B exit just raised $25M for a robotics startup",
        "All3, a construction robotics company, has raised $25 million in a seed round led by RTP Global.",
        score=90,
    )
    direct = _candidate(
        "direct",
        "All3 raises $25M to expand its construction robotics platform",
        "All3 has raised $25 million in a seed round led by RTP Global to expand its robotics platform for jobsites.",
        score=87,
    )

    suppressed = suppress_same_event_funding_duplicates([clickbait, direct])

    assert suppressed[0].suppressed_item_id == "clickbait"
    assert suppressed[0].representative_item_id == "direct"


def _partnership_candidate(
    item_id: str,
    title: str,
    preview: str,
    score: int = 80,
    published_hours_ago: int = 1,
    partnership_event: bool = True,
) -> SendStageCandidate:
    return SendStageCandidate(
        normalized_item_id=item_id,
        canonical_url=f"https://example.com/{item_id}",
        title=title,
        text_preview=preview,
        published_ts=datetime.now(timezone.utc) - timedelta(hours=published_hours_ago),
        score=score,
        event_flags={"partnership_event": partnership_event},
    )


def test_partnership_duplicates_collapse_to_one_representative() -> None:
    left = _partnership_candidate(
        "a",
        "Flex and Teradyne Robotics expand partnership to scale intelligent automation across global manufacturing",
        "Flex and Teradyne Robotics are expanding their collaboration across global manufacturing automation.",
        score=86,
    )
    right = _partnership_candidate(
        "b",
        "Teradyne Robotics partners with Flex to scale intelligent automation across global manufacturing",
        "Teradyne Robotics and Flex are expanding a strategic partnership for manufacturing automation.",
        score=91,
    )

    suppressed = suppress_same_event_funding_duplicates([left, right])

    assert suppressed == [
        SuppressedDuplicate(
            suppressed_item_id="a",
            representative_item_id="b",
            reason="duplicate_same_partnership_event_shortlist",
        )
    ]


def test_same_company_different_partner_does_not_collapse_for_partnerships() -> None:
    left = _partnership_candidate(
        "a",
        "NEURA Robotics partners with Dassault Systemes on virtual twins",
        "NEURA Robotics and Dassault Systemes are partnering on virtual twins.",
    )
    right = _partnership_candidate(
        "b",
        "NEURA Robotics partners with AWS on physical AI tooling",
        "NEURA Robotics and AWS are partnering on physical AI tooling.",
    )

    assert suppress_same_event_funding_duplicates([left, right]) == []


def test_same_entities_without_partnership_flag_do_not_collapse() -> None:
    left = _partnership_candidate(
        "a",
        "Flex and Teradyne Robotics expand partnership to scale intelligent automation",
        "Flex and Teradyne Robotics are expanding their collaboration.",
        partnership_event=False,
    )
    right = _partnership_candidate(
        "b",
        "Teradyne Robotics partners with Flex to scale intelligent automation",
        "Teradyne Robotics and Flex are expanding a strategic partnership.",
        partnership_event=False,
    )

    assert suppress_same_event_funding_duplicates([left, right]) == []


def test_ambiguous_partnership_headline_without_two_entities_does_not_collapse() -> None:
    left = _partnership_candidate(
        "a",
        "Strategic partnership expands intelligent automation efforts",
        "A strategic partnership expands automation efforts across manufacturing.",
    )
    right = _partnership_candidate(
        "b",
        "Partnership supports broader manufacturing automation rollout",
        "The collaboration supports automation rollout across manufacturing.",
    )

    assert suppress_same_event_funding_duplicates([left, right]) == []


def test_higher_score_wins_for_same_partnership_event() -> None:
    lower = _partnership_candidate(
        "low",
        "Flex and Teradyne Robotics expand partnership across manufacturing",
        "Flex and Teradyne Robotics are expanding their collaboration.",
        score=84,
    )
    higher = _partnership_candidate(
        "high",
        "Teradyne Robotics partners with Flex to scale intelligent automation across global manufacturing",
        "Teradyne Robotics and Flex are expanding a strategic partnership for manufacturing automation.",
        score=93,
    )

    suppressed = suppress_same_event_funding_duplicates([lower, higher])

    assert suppressed[0].suppressed_item_id == "low"
    assert suppressed[0].representative_item_id == "high"
