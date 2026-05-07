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
        "Sereact announces EUR110M Series B round",
        "Sereact has raised EUR110 million in Series B financing to expand its AI robotics stack for warehouse and industrial automation.",
    )

    assert summary is not None
    assert summary == "Sereact has announced EUR110M Series B round."


def test_generate_fallback_summary_rejects_dangling_comparison_tail() -> None:
    summary = generate_fallback_summary(
        "Concrete Loses 32% More Heat Than Mass Timber in Chile's Cold Zones",
        "A study of buildings in Chile's cold climate zones found that concrete structures lose between 26% and 32% more heat than mass timber buildings of identical typology once.",
    )

    assert summary is not None
    assert summary.endswith("identical typology.")
    assert " once." not in summary


def test_generate_fallback_summary_strips_dangling_location_fragment() -> None:
    summary = generate_fallback_summary(
        "University of Toronto installs KUKA KR210 arm for sub-0.1mm mass timber milling",
        "The department commissioned a 3.5-metre KUKA Quantec KR210 robotic arm, described as among the largest installed at a.",
    )

    assert summary is not None
    assert "installed at a." not in summary


def test_generate_fallback_summary_strips_dangling_automated_tail() -> None:
    summary = generate_fallback_summary(
        "Comau and Aptiv partner on AI-powered robotics and autonomous industrial automation systems",
        "Industrial automation specialist Comau is collaborating with technology company Aptiv to explore the co-development of next-generation intelligent automation solutions designed to help industrial customers operate more safely. The agreement establishes a framework for the two companies to evaluate joint development in key areas of focus including advanced robotics, autonomous systems, and automated.",
    )

    assert summary is not None
    assert "and automated." not in summary
    assert "advanced robotics, autonomous systems." in summary
