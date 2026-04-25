"""Radar summary generation orchestration."""

from __future__ import annotations

import logging

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem, SummaryResult
from all3_radar.summarization.fallback_summary import (
    SENTENCE_SPLIT_RE,
    generate_fallback_summary,
    sanitize_summary_text,
)
from all3_radar.summarization.gemini_client import GeminiClient, GeminiUnavailableError

LOGGER = logging.getLogger(__name__)


def _sentence_count(text: str | None) -> int:
    if not text:
        return 0
    return len([sentence for sentence in SENTENCE_SPLIT_RE.split(text) if sentence.strip()])


def summarize_candidate(
    item: StoredNormalizedItem,
    decision: RankedDecision,
    gemini_client: GeminiClient,
) -> SummaryResult:
    fallback = generate_fallback_summary(item.title, item.text_preview)

    if decision.is_shortlisted and gemini_client.is_available:
        try:
            summary_text, override = gemini_client.generate_summary(
                title=item.title,
                preview=item.text_preview,
                borderline=decision.is_borderline,
            )
            summary_text = sanitize_summary_text(item.title, summary_text)
            if summary_text:
                if fallback and _sentence_count(summary_text) < 2 and _sentence_count(fallback) >= 2:
                    return SummaryResult(
                        summary_text=fallback,
                        used_gemini=False,
                        gemini_decision_override=override,
                    )
                return SummaryResult(
                    summary_text=summary_text,
                    used_gemini=True,
                    gemini_decision_override=override,
                )
        except GeminiUnavailableError as exc:
            LOGGER.warning("Gemini unavailable for item=%s reason=%s", item.normalized_item_id, exc)

    return SummaryResult(summary_text=fallback, used_gemini=False, gemini_decision_override=None)
