from datetime import datetime, timezone

from all3_radar.pipeline.funding_sent_history import funding_key_from_text, same_funding_event


def _funding_key(title: str, preview: str, published_ts: datetime | None = None):
    return funding_key_from_text(
        title=title,
        preview=preview,
        published_ts=published_ts or datetime.now(timezone.utc),
        event_flags={"funding_event": True},
    )


def test_same_company_different_amount_does_not_match() -> None:
    left = _funding_key(
        "All3 raises $25M to scale construction robotics",
        "All3 has raised $25 million in a seed round led by RTP Global.",
    )
    right = _funding_key(
        "All3 raises $40M to scale construction robotics",
        "All3 has raised $40 million in a seed round led by RTP Global.",
    )

    assert left is not None and right is not None
    assert same_funding_event(left, right) is False


def test_same_company_different_round_does_not_match() -> None:
    left = _funding_key(
        "All3 raises $25M seed round to scale construction robotics",
        "All3 has raised $25 million in a seed round led by RTP Global.",
    )
    right = _funding_key(
        "All3 raises $25M Series A to scale construction robotics",
        "All3 has raised $25 million in a Series A led by RTP Global.",
    )

    assert left is not None and right is not None
    assert same_funding_event(left, right) is False


def test_different_company_same_amount_does_not_match() -> None:
    left = _funding_key(
        "All3 raises $25M to scale construction robotics",
        "All3 has raised $25 million in a seed round led by RTP Global.",
    )
    right = _funding_key(
        "Kewazo raises $25M to scale construction robotics",
        "Kewazo has raised $25 million in a seed round led by RTP Global.",
    )

    assert left is not None and right is not None
    assert same_funding_event(left, right) is False


def test_same_robotic_hand_company_valuation_variants_do_match() -> None:
    left = _funding_key(
        "Report: China Robotic Hand Maker Linkerbot Targets $6B Valuation",
        (
            "Chinese robotics startup Linkerbot is targeting a $6 billion valuation in its next funding round, "
            "doubling the valuation it secured in a recently completed financing as investor interest rises."
        ),
    )
    right = _funding_key(
        "Linkerbot hits $3B valuation with Ant Group, HongShan to produce robotic hands that perform delicate tasks",
        (
            "Chinese robotics startup Linkerbot has closed a Series B+ round at a $3 billion valuation "
            "to scale robotic hands for humanoid robots."
        ),
    )

    assert left is not None and right is not None
    assert same_funding_event(left, right) is True


def test_generic_profile_without_funding_signal_has_no_key() -> None:
    key = funding_key_from_text(
        title="Inside All3's push into construction robotics",
        preview="All3 is building robotics systems for construction productivity.",
        published_ts=datetime.now(timezone.utc),
        event_flags={"funding_event": False},
    )

    assert key is None


def test_xpanner_cross_source_titles_do_match_same_funding_event() -> None:
    left = _funding_key(
        "Exclusive: Xpanner Lands $18M To Offer Automation As A Service To Construction Sites",
        "Xpanner, a startup automating construction work through robotics and physical AI technology, has raised $18 million in a Series B round.",
    )
    right = _funding_key(
        "Xpanner Secures $18M in Series B Bridge Funding for AI-Powered Construction Automation Platform",
        "Xpanner has secured $18M in Series B bridge funding to expand an AI-powered construction automation platform.",
    )

    assert left is not None and right is not None
    assert left.entity == "xpanner"
    assert right.entity == "xpanner"
    assert same_funding_event(left, right) is True
