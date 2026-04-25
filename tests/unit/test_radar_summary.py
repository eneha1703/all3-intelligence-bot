from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import RankedDecision, StoredNormalizedItem
from all3_radar.summarization.radar_summary import summarize_candidate


def _make_item(title: str, preview: str) -> StoredNormalizedItem:
    now = datetime.now(timezone.utc)
    return StoredNormalizedItem(
        normalized_item_id="item-1",
        raw_item_id="raw-1",
        source_id="source-1",
        canonical_url="https://example.com/story",
        domain="example.com",
        title=title,
        text_preview=preview,
        published_ts=now,
        collected_ts=now,
        layer=SourceLayer.DIRECT,
        is_wrapper=False,
        directness_rank=100,
        metadata={},
    )


def _make_decision() -> RankedDecision:
    return RankedDecision(
        relevance_status="keep",
        send_status="stored_only",
        skip_reason=None,
        score=50,
        signals={"competitor_count": 0, "event_flags": {}},
        is_shortlisted=True,
        is_borderline=False,
    )


class _ThinGemini:
    is_available = True

    def generate_summary(self, title: str, preview: str | None, borderline: bool = False) -> tuple[str, str | None]:
        return ("ABB Robotics said its new PoWa family of cobots addresses a long-standing gap in the market.", None)


def test_summarize_candidate_prefers_denser_fallback_over_thin_gemini() -> None:
    item = _make_item(
        "ABB Robotics launches PoWa cobot family targeting industrial tasks",
        "ABB Robotics said its new PoWa family of cobots addresses a long-standing gap in the market between traditional cobots.",
    )

    result = summarize_candidate(item, _make_decision(), _ThinGemini())

    assert result.summary_text is not None
    assert "ABB Robotics has launched PoWa cobot family targeting industrial tasks." in result.summary_text
    assert "traditional cobots." in result.summary_text
    assert result.used_gemini is False
