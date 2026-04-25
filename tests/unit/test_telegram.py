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
    assert (
        card.text
        == (
            "<b>Kewazo raises funding for construction robotics rollout</b>\n\n"
            "The company said the round will support jobsite deployment expansion.\n\n"
            '<a href="https://example.com/story">Link</a>'
        )
    )


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


def test_build_news_card_strips_insider_brief_prefix() -> None:
    card = build_news_card(
        headline="Teradyne expands industrial automation footprint",
        summary_text=(
            "Insider Brief: Teradyne is expanding its industrial automation footprint through a new partnership. "
            "The deal adds more robot deployment capacity across manufacturing operations."
        ),
        url="https://example.com/insider-story",
    )

    assert card is not None
    assert "Insider Brief" not in card.text
    assert "industrial automation footprint" in card.text


def test_build_news_card_skips_low_information_commentary_summary() -> None:
    card = build_news_card(
        headline="Physical AI panel highlights the future of robotics",
        summary_text=(
            "The panel discusses the future of robotics and shares insights on human-robot interactions. "
            "It explores where the market may go next."
        ),
        url="https://example.com/commentary-story",
    )

    assert card is None
