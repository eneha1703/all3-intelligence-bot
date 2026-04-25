from pathlib import Path

from all3_radar.sources.registry import load_source_registry


def test_source_registry_loads() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sources = load_source_registry(repo_root / "config" / "sources.yaml")
    assert sources
    assert any(source["id"] == "google_news_competitors" for source in sources)
