from pathlib import Path

from all3_radar.pipeline.competitors import detect_competitor_matches, load_competitor_catalog


def test_competitor_matching_handles_case_and_format_variants() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    catalog = load_competitor_catalog(repo_root / "config" / "competitors.yaml")

    matches = detect_competitor_matches(
        title="Factory OS expands modular production with KEWAZO partner deployment",
        preview="The article also references Reframe-Systems and Intelligent City activity.",
        catalog=catalog,
    )

    names = sorted({match.competitor_name for match in matches})
    assert "Factory_OS" in names
    assert "Kewazo" in names
    assert "Reframe Systems" in names
    assert "Intelligent City" in names
