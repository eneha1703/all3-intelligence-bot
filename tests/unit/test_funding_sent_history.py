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


def test_generic_profile_without_funding_signal_has_no_key() -> None:
    key = funding_key_from_text(
        title="Inside All3's push into construction robotics",
        preview="All3 is building robotics systems for construction productivity.",
        published_ts=datetime.now(timezone.utc),
        event_flags={"funding_event": False},
    )

    assert key is None
