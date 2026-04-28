from all3_radar.summarization.fallback_summary import generate_fallback_summary


def test_generate_fallback_summary_uses_title_plus_preview_when_preview_is_thin() -> None:
    summary = generate_fallback_summary(
        "Messer Construction breaks ground on $280M university health building",
        "The six-story, 257,000-square-foot health education facility will feature modular teaching spaces for multiple professions.",
    )

    assert summary is not None
    assert "Messer Construction has broken ground on $280M university health building." in summary
    assert "257,000-square-foot health education facility will feature modular teaching spaces" in summary


def test_generate_fallback_summary_builds_two_sentence_industrial_card() -> None:
    summary = generate_fallback_summary(
        "ABB Robotics launches PoWa cobot family targeting industrial tasks",
        "ABB Robotics said its new PoWa family of cobots addresses a long-standing gap in the market between traditional cobots.",
    )

    assert summary is not None
    assert "ABB Robotics has launched PoWa cobot family targeting industrial tasks." in summary
    assert "addresses a long-standing gap in the market between traditional cobots." in summary


def test_generate_fallback_summary_prefers_title_sentence_for_single_sentence_announce_preview() -> None:
    summary = generate_fallback_summary(
        "Sereact announces €110M Series B round",
        "Sereact has raised €110 million in Series B financing to expand its AI robotics stack for warehouse and industrial automation.",
    )

    assert summary is not None
    assert summary == "Sereact has announced €110M Series B round."
