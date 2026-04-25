from all3_radar.delivery.telegram import build_news_card


def test_build_news_card_formats_clean_message() -> None:
    card = build_news_card(
        headline="Kewazo raises funding for construction robotics rollout",
        summary_text=(
            "Kewazo raises funding for construction robotics rollout. "
            "The company said the round will support jobsite deployment expansion."
        ),
        url="https://example.com/story",
    )

    assert card is not None
    assert "<b>Kewazo raises funding for construction robotics rollout</b>" in card.text
    assert "The company said the round will support jobsite deployment expansion." in card.text
    assert 'href="https://example.com/story"' in card.text


def test_build_news_card_skips_truncated_or_boilerplate_summary() -> None:
    card = build_news_card(
        headline="Accenture, Vodafone, and SAP to pilot humanoid robots in the warehouse",
        summary_text=(
            "The humanoids in the pilot are powered by Accenture's Robot Brain solution... "
            "The post Accenture, Vodafone, and SAP to pilot humanoid robots in the warehouse appeared first on The Robot Report."
        ),
        url="https://example.com/story",
    )

    assert card is None


def test_build_news_card_strips_photo_credit_sentences() -> None:
    card = build_news_card(
        headline="Flex and Teradyne Robotics expand partnership to scale intelligent automation",
        summary_text=(
            "Flex manufacturing campus. Courtesy of Flex. "
            "Flex and Teradyne Robotics are expanding their collaboration to deploy automation across manufacturing sites."
        ),
        url="https://example.com/story",
    )

    assert card is not None
    assert "Courtesy of Flex" not in card.text
    assert "deploy automation across manufacturing sites." in card.text


def test_build_news_card_accepts_bracketed_ellipsis_after_complete_sentences() -> None:
    card = build_news_card(
        headline="Flex and Teradyne Robotics expand partnership to scale intelligent automation",
        summary_text=(
            "Flex and Teradyne Robotics are expanding their collaboration across global manufacturing. "
            "Flex will deploy robotics in production facilities while manufacturing key components for Teradyne [...]."
        ),
        url="https://example.com/story",
    )

    assert card is not None
    assert "[...]" not in card.text
    assert "global manufacturing." in card.text
