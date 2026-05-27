from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.wood_central import parse_wood_central_posts


def test_parse_wood_central_posts_uses_content_to_build_richer_snippet() -> None:
    source = SourceDefinition(
        id="wood_central_api",
        name="Wood Central",
        kind=SourceKind.API,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="wood_central_api",
        url="https://woodcentral.com.au",
        priority=1,
    )
    collected_at = datetime(2026, 5, 27, tzinfo=timezone.utc)
    payload = """
    [
      {
        "id": 42,
        "slug": "engineered-wood-mid-rise-housing",
        "link": "https://woodcentral.com.au/engineered-wood-mid-rise-housing/",
        "date_gmt": "2026-05-27T07:00:00",
        "title": {"rendered": "Engineered Wood Products Find Their Sweet Spot With Mid-Rise Housing"},
        "excerpt": {"rendered": "<p>Engineered wood is moving into mid-rise housing.</p>"},
        "content": {"rendered": "<p>Mid-rise residential formats are giving engineered wood a clearer adoption path.</p><p>The shift matters because denser housing formats can create repeatable demand beyond one-off showcase buildings.</p>"}
      }
    ]
    """

    items = parse_wood_central_posts(payload, source=source, collected_at=collected_at)

    assert len(items) == 1
    assert items[0].snippet is not None
    assert "Mid-rise residential formats are giving engineered wood a clearer adoption path." in items[0].snippet
    assert "repeatable demand beyond one-off showcase buildings" in items[0].snippet
