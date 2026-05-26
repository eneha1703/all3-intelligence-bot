import importlib.util
from pathlib import Path


def _load_preview_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "web_discovery_preview.py"
    spec = importlib.util.spec_from_file_location("web_discovery_preview", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


preview = _load_preview_module()


def test_build_preview_markdown_renders_telegram_html_cards(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-05-26T15:18:39+00:00",
        "accepted_candidates": [
            {
                "candidate": {
                    "title": "Robot maker opens factory",
                    "url": "https://example.com/factory",
                    "source_name": "Example Robotics",
                    "confidence": "high",
                    "summary": (
                        "Robot maker opened a factory for industrial automation systems. "
                        "The company says the site will support scaled manufacturing. "
                        "A third sentence should not be included."
                    ),
                }
            },
            {
                "candidate": {
                    "title": "Industrial AI partnership announced",
                    "url": "https://stocktitan.net/news/example",
                    "source_name": "Stock Titan / PR Newswire",
                    "confidence": "high",
                    "summary": "A supplier announced an industrial AI partnership for factory edge systems.",
                }
            },
        ],
    }

    markdown = preview.build_preview_markdown(payload, source_path=tmp_path / "web-discovery.json")

    assert "Web Discovery Telegram Preview" in markdown
    assert "Candidate 1: likely_post" in markdown
    assert "Candidate 2: verify_primary_source" in markdown
    assert "<b>Robot maker opens factory</b>" in markdown
    assert '<a href="https://example.com/factory">Link</a>' in markdown
    assert "A third sentence should not be included" not in markdown
