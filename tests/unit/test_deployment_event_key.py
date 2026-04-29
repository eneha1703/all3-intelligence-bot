from datetime import datetime, timedelta, timezone

from all3_radar.pipeline.deployment_event_key import deployment_key_from_text, same_deployment_event


def _deployment_key(
    title: str,
    preview: str,
    *,
    published_ts: datetime | None = None,
    deployment_event: bool = True,
):
    return deployment_key_from_text(
        title=title,
        preview=preview,
        published_ts=published_ts or datetime.now(timezone.utc),
        event_flags={"deployment_event": deployment_event},
    )


def test_hexagon_schaeffler_rollout_stories_produce_matching_keys() -> None:
    left = _deployment_key(
        "Hexagon and Schaeffler to install 1,000 Aeon humanoids across global factory network",
        "Hexagon and Schaeffler said the rollout will deploy 1,000 Aeon humanoids across factories worldwide.",
    )
    right = _deployment_key(
        "Schaeffler plans to deploy 1,000 Hexagon humanoids by 2032",
        "Schaeffler said it will deploy 1,000 Hexagon humanoids across its global operations by 2032.",
    )

    assert left is not None and right is not None
    assert same_deployment_event(left, right) is True


def test_same_entities_different_quantity_does_not_match() -> None:
    left = _deployment_key(
        "Hexagon and Schaeffler to install 1,000 Aeon humanoids across factories",
        "The companies will deploy 1,000 Aeon humanoids across factory sites.",
    )
    right = _deployment_key(
        "Hexagon and Schaeffler to install 500 Aeon humanoids across factories",
        "The companies will deploy 500 Aeon humanoids across factory sites.",
    )

    assert left is not None and right is not None
    assert same_deployment_event(left, right) is False


def test_same_quantity_different_entities_does_not_match() -> None:
    left = _deployment_key(
        "Hexagon and Schaeffler to install 1,000 Aeon humanoids across factories",
        "The companies will deploy 1,000 Aeon humanoids across factory sites.",
    )
    right = _deployment_key(
        "ABB and SKF to install 1,000 Aeon humanoids across factories",
        "The companies will deploy 1,000 Aeon humanoids across factory sites.",
    )

    assert left is not None and right is not None
    assert same_deployment_event(left, right) is False


def test_deployment_event_false_returns_none() -> None:
    key = _deployment_key(
        "Hexagon and Schaeffler to install 1,000 Aeon humanoids across factories",
        "The companies will deploy 1,000 Aeon humanoids across factory sites.",
        deployment_event=False,
    )

    assert key is None


def test_generic_humanoid_strategy_article_returns_none() -> None:
    key = _deployment_key(
        "How humanoid robotics strategy is evolving in Europe",
        "A strategy article on how manufacturers are thinking about the humanoid market over the next decade.",
    )

    assert key is None


def test_missing_program_and_quantity_returns_none() -> None:
    key = _deployment_key(
        "Hexagon and Schaeffler discuss deployment plans for factory automation",
        "The companies outlined deployment priorities for factory automation and robotics programs.",
    )

    assert key is None


def test_date_window_is_respected() -> None:
    now = datetime.now(timezone.utc)
    left = _deployment_key(
        "Hexagon and Schaeffler to install 1,000 Aeon humanoids across factories",
        "The companies will deploy 1,000 Aeon humanoids across factory sites.",
        published_ts=now,
    )
    right = _deployment_key(
        "Schaeffler plans to deploy 1,000 Hexagon humanoids by 2032",
        "Schaeffler said it will deploy 1,000 Hexagon humanoids across its global operations by 2032.",
        published_ts=now + timedelta(days=8),
    )

    assert left is not None and right is not None
    assert same_deployment_event(left, right) is False
