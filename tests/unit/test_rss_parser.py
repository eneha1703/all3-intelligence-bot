from datetime import datetime, timezone

from all3_radar.domain.enums import SourceKind, SourceLayer
from all3_radar.domain.models import SourceDefinition
from all3_radar.sources.rss import parse_rss_items


def _rss_source() -> SourceDefinition:
    return SourceDefinition(
        id="construction_briefing_rss",
        name="Construction Briefing",
        kind=SourceKind.RSS,
        layer=SourceLayer.DIRECT,
        is_direct_source=True,
        is_wrapper=False,
        enabled=True,
        parser="generic_rss",
        url="https://constructionbriefing.com/rss",
        priority=85,
        tags=("construction",),
    )


def test_parse_rss_items_recovers_from_bare_ampersands() -> None:
    feed_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Timber & modular housing project moves ahead</title>
      <link>https://example.com/story</link>
      <description>New modular project pairs CLT & off-site construction.</description>
      <pubDate>Fri, 02 May 2026 10:00:00 GMT</pubDate>
      <guid>story-1</guid>
    </item>
  </channel>
</rss>
"""

    items = parse_rss_items(feed_text=feed_text, source=_rss_source(), collected_at=datetime(2026, 5, 2, tzinfo=timezone.utc))

    assert len(items) == 1
    assert items[0].title == "Timber & modular housing project moves ahead"
    assert items[0].snippet == "New modular project pairs CLT & off-site construction."
