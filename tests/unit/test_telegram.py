from all3_radar.delivery.telegram import build_inline_reply_markup, build_news_card, build_replay_card


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


def test_build_news_card_keeps_three_short_factual_sentences_when_useful() -> None:
    card = build_news_card(
        headline="Robotics firm opens new automation plant",
        summary_text=(
            "The company opened a new automation plant in Ohio. "
            "The facility adds production capacity for robot components. "
            "It will supply industrial customers across North America."
        ),
        url="https://example.com/plant-story",
    )

    assert card is not None
    assert "opened a new automation plant in Ohio." in card.text
    assert "adds production capacity for robot components." in card.text
    assert "industrial customers across North America." in card.text


def test_build_news_card_trims_overlong_clause_heaviness() -> None:
    card = build_news_card(
        headline="Neura Robotics partners with Dassault Systemes",
        summary_text=(
            "Neura Robotics is partnering with Dassault Systemes to connect robot training in virtual environments with real-world deployment. "
            "The agreement links Neura's robotics platform with Dassault's 3DEXPERIENCE virtual twin platform, creating a closed-loop system where robots learn in simulation, operate in physical environments, and continuously improve across both."
        ),
        url="https://example.com/neura-story",
    )

    assert card is not None
    assert "creating a closed-loop system" not in card.text
    assert "3DEXPERIENCE virtual twin platform." in card.text


def test_build_news_card_removes_trailing_according_fragment() -> None:
    card = build_news_card(
        headline="Schaeffler and Hexagon Robotics partner for humanoid robots",
        summary_text=(
            "Schaeffler is deepening its push into humanoid robotics through a new partnership with Hexagon Robotics. "
            "The agreement covers the development and supply of high-precision rotary actuators used in joints such as shoulders and elbows in humanoid robots, according to the companies."
        ),
        url="https://example.com/schaeffler-story",
    )

    assert card is not None
    assert "according." not in card.text
    assert "according to the companies" not in card.text
    assert "used in joints such as shoulders and elbows in humanoid robots." in card.text


def test_build_news_card_drops_dangling_between_fragment_sentence() -> None:
    card = build_news_card(
        headline="Kawasaki opens Silicon Valley Physical AI Center to accelerate industrial robotics deployment",
        summary_text=(
            "Kawasaki Heavy Industries has opened the Kawasaki Physical AI Center San Jose, a dedicated facility in Silicon Valley focused on developing real-world physical AI applications for industrial robotics. "
            "The center is designed to accelerate collaboration between Japanese and."
        ),
        url="https://example.com/kawasaki-story",
    )

    assert card is not None
    assert "between Japanese and" not in card.text
    assert "developing real-world physical AI applications for industrial robotics." in card.text


def test_build_replay_card_prepends_clear_replay_label() -> None:
    card = build_news_card(
        headline="Mass timber premiums run six to ten times higher than concrete and steel",
        summary_text=(
            "A quantified cost comparison suggests mass timber premiums remain a major adoption barrier for commercial viability and timber scaling."
        ),
        url="https://example.com/timber-story",
    )

    assert card is not None
    replay_card = build_replay_card(card, "[REPLAY / MANUAL VALIDATION 2026-04-24..2026-04-28]")

    assert replay_card.text.startswith("<i>[REPLAY / MANUAL VALIDATION 2026-04-24..2026-04-28]</i>")
    assert "<b>Mass timber premiums run six to ten times higher than concrete and steel</b>" in replay_card.text


def test_build_news_card_has_no_actions_by_default() -> None:
    card = build_news_card(
        headline="Unitree launches upper-body humanoid robot at $4,290",
        summary_text="Unitree has unveiled a low-cost upper-body humanoid robot aimed at entry-level use.",
        url="https://example.com/unitree",
    )

    assert card is not None
    assert card.action_buttons == ()
    assert build_inline_reply_markup(card.action_buttons) is None
