from datetime import datetime, timezone
from pathlib import Path

import pytest

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.parsers.destatis_press import parse_destatis_press_listing, parse_destatis_published_ts


def _destatis_source() -> SourceDefinition:
    return SourceDefinition(
        id="destatis_press_listing",
        name="Destatis Press",
        kind=SourceKind.LISTING,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="destatis_press",
        url="https://www.destatis.de/EN/Press/_node.html",
        priority=75,
        tags=("policy", "statistics"),
    )


def test_parse_destatis_published_ts_supports_german_press_format() -> None:
    published_ts = parse_destatis_published_ts("Pressemitteilung Nr. 144 vom 24. April 2026")

    assert published_ts == datetime(2026, 4, 24, tzinfo=timezone.utc)


def test_parse_destatis_press_listing_extracts_clean_items() -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "destatis_press_listing.html"
    html = (
        fixture_path.read_text(encoding="utf-8")
        .replace("__FRESH_DATE_GERMAN__", "24. April 2026")
        .replace("__STALE_DATE_GERMAN__", "10. März 2026")
    )

    items = parse_destatis_press_listing(
        feed_text=html,
        source=_destatis_source(),
        collected_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
    )

    assert len(items) == 2
    assert items[0].url == "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/04/PD26_144_441.html"
    assert items[0].published_ts == datetime(2026, 4, 24, tzinfo=timezone.utc)
    assert items[0].external_id == "PD26_144_441.html"
    assert items[0].title == "Auftragseingang im Bauhauptgewerbe im Februar 2026: +7,3 % zum Vormonat"
    assert "Bauhauptgewerbe" in (items[0].snippet or "")
    assert all(item.published_ts is not None for item in items)


def test_parse_destatis_press_listing_fails_when_no_trustworthy_dates() -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "destatis_press_listing.html"
    html = fixture_path.read_text(encoding="utf-8").replace("__FRESH_DATE_GERMAN__", "").replace(
        "__STALE_DATE_GERMAN__", ""
    )

    with pytest.raises(ValueError, match="could not extract trustworthy published dates"):
        parse_destatis_press_listing(
            feed_text=html,
            source=_destatis_source(),
            collected_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
        )


def test_parse_destatis_press_listing_normalizes_duplicated_article_prefix() -> None:
    html = """
    <div class="news">
      <a href="/DE/Presse/Pressemitteilungen/DE/Presse/Pressemitteilungen/2026/05/PD26_166_3111.html">
        Baugenehmigungen f&uuml;r Wohnungen im April 2026
      </a>
      <div class="copytext">
        <time>21. Mai 2026</time>
        Pressemitteilung Nr. 166 vom 21. Mai 2026
      </div>
    </div>
    """

    items = parse_destatis_press_listing(
        feed_text=html,
        source=_destatis_source(),
        collected_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].url == "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/05/PD26_166_3111.html"
    assert items[0].external_id == "PD26_166_3111.html"
