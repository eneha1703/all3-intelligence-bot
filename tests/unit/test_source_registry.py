from pathlib import Path

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.sources.registry import load_source_registry


def test_source_registry_loads_typed_sources() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    registry = load_source_registry(repo_root / "config" / "sources.yaml")

    assert registry.all()
    google_source = registry.get("google_news_competitors")
    assert google_source.kind == SourceKind.GOOGLE_COMPETITOR
    assert google_source.layer == SourceLayer.GOOGLE_COMPETITOR
    assert google_source.is_wrapper is True
    assert registry.get("construction_briefing_rss").enabled is True
    haufe_source = registry.get("haufe_immobilien_listing")
    assert haufe_source.enabled is True
    assert haufe_source.kind == SourceKind.LISTING
    assert haufe_source.parser == "haufe_immobilien"
    assert haufe_source.supports_first_slice is True
    assert registry.get("interesting_engineering_rss").enabled is True
