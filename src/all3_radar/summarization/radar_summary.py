"""Radar summary generation orchestration."""

from __future__ import annotations

import logging

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem, SummaryResult
from all3_radar.summarization.fallback_summary import compress_to_two_sentences, generate_fallback_summary, remove_repeated_headline
from all3_radar.summarization.gemini_client import GeminiClient, GeminiUnavailableError

LOGGER = logging.getLogger(__name__)


def summarize_candidate(
    item: StoredNormalizedItem,
    decision: RankedDecision,
    gemini_client: GeminiClient,
) -> SummaryResult:
    if decision.is_shortlisted and gemini_client.is_available:
        try:
            summary_text, override = gemini_client.generate_summary(
                title=item.title,
                preview=item.text_preview,
                borderline=decision.is_borderline,
            )
            summary_text = compress_to_two_sentences(remove_repeated_headline(summary_text, item.title))
            if summary_text:
                return SummaryResult(
                    summary_text=summary_text,
                    used_gemini=True,
                    gemini_decision_override=override,
                )
        except GeminiUnavailableError as exc:
            LOGGER.warning("Gemini unavailable for item=%s reason=%s", item.normalized_item_id, exc)

    fallback = generate_fallback_summary(item.title, item.text_preview)
    return SummaryResult(summary_text=fallback, used_gemini=False, gemini_decision_override=None)
