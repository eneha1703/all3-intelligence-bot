from datetime import datetime, timezone

from all3_radar.domain.enums import SourceLayer
from all3_radar.domain.models import RankedDecision, StoredNormalizedItem
from all3_radar.summarization.radar_summary import maybe_translate_delivery_card, summarize_candidate


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


class _TranslatingGemini:
    is_available = True

    def rewrite_delivery_card(
        self,
        *,
        title: str,
        summary: str,
        source_language: str,
        target_language: str = "English",
    ) -> tuple[str, str]:
        return (
            "German building permits fall again as housing supply slows",
            "Official statistics show building permits declined again, pointing to a weaker housing supply pipeline.",
        )


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


def test_maybe_translate_delivery_card_rewrites_german_sendable_story_to_english() -> None:
    item = _make_item(
        "Baugenehmigungen sinken erneut",
        "Die Zahl der Baugenehmigungen ist erneut gesunken.",
    )
    item = StoredNormalizedItem(
        **{
            **item.__dict__,
            "source_id": "destatis_press_listing",
            "metadata": {"origin_language": "de", "delivery_language": "en"},
        }
    )

    headline, summary, translated, reason = maybe_translate_delivery_card(
        item=item,
        headline=item.title,
        summary_text=item.text_preview,
        gemini_client=_TranslatingGemini(),
    )

    assert translated is True
    assert reason is None
    assert headline == "German building permits fall again as housing supply slows"
    assert "Official statistics show building permits declined again" in summary
