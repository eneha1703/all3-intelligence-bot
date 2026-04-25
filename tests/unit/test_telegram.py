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
