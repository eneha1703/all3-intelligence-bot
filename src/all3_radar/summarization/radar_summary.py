"""Radar summary generation orchestration."""

from __future__ import annotations

import logging
import re

from all3_radar.domain.models import RankedDecision, StoredNormalizedItem, SummaryResult
from all3_radar.summarization.fallback_summary import (
    SENTENCE_SPLIT_RE,
    generate_fallback_summary,
    sanitize_summary_text,
)
from all3_radar.summarization.gemini_client import GeminiClient, GeminiUnavailableError

LOGGER = logging.getLogger(__name__)
TITLE_PATTERNS = (
    (re.compile(r"^(?P<subject>.+?) announces (?P<object>.+)$", re.IGNORECASE), "announces"),
    (re.compile(r"^(?P<subject>.+?) launches (?P<object>.+)$", re.IGNORECASE), "launches"),
    (re.compile(r"^(?P<subject>.+?) raises (?P<object>.+)$", re.IGNORECASE), "raises"),
    (re.compile(r"^(?P<subject>.+?) partners with (?P<object>.+)$", re.IGNORECASE), "partners_with"),
    (re.compile(r"^(?P<subject>.+?) opens (?P<object>.+)$", re.IGNORECASE), "opens"),
)


def _sentence_count(text: str | None) -> int:
    if not text:
        return 0
    return len([sentence for sentence in SENTENCE_SPLIT_RE.split(text) if sentence.strip()])


def _subject_auxiliaries(subject: str) -> tuple[str, str]:
    plural = " and " in subject.lower()
    return ("have", "are") if plural else ("has", "is")


def _headline_fallback_summary(headline: str) -> str | None:
    cleaned_headline = headline.strip()
    if not cleaned_headline:
        return None

    for pattern, kind in TITLE_PATTERNS:
        match = pattern.match(cleaned_headline)
        if not match:
            continue

        subject = match.group("subject").strip()
        obj = match.group("object").strip().rstrip(".")
        have, be = _subject_auxiliaries(subject)
        if kind == "announces":
            candidate = f"{subject} {have} announced {obj}."
        elif kind == "launches":
            candidate = f"{subject} {have} launched {obj}."
        elif kind == "raises":
            candidate = f"{subject} {have} raised {obj}."
        elif kind == "partners_with":
            candidate = f"{subject} {have} partnered with {obj}."
        else:
            candidate = f"{subject} {be} opening {obj}."

        sanitized = sanitize_summary_text(cleaned_headline, candidate)
        if sanitized:
            return sanitized

    if len(cleaned_headline.split()) >= 6 and cleaned_headline[-1] not in ".!?":
        return sanitize_summary_text(cleaned_headline, f"{cleaned_headline}.")
    return None


def _build_delivery_fallback(item: StoredNormalizedItem) -> str | None:
    for candidate in (
        generate_fallback_summary(item.title, item.text_preview),
        sanitize_summary_text(item.title, item.text_preview),
        _headline_fallback_summary(item.title),
    ):
        if candidate:
            return candidate
    return None


def summarize_candidate(
    item: StoredNormalizedItem,
    decision: RankedDecision,
    gemini_client: GeminiClient,
) -> SummaryResult:
    fallback = _build_delivery_fallback(item)

    if decision.is_shortlisted and gemini_client.is_available:
        try:
            summary_text, override = gemini_client.generate_summary(
                title=item.title,
                preview=item.text_preview,
                borderline=decision.is_borderline,
            )
            summary_text = sanitize_summary_text(item.title, summary_text)
            if summary_text:
                if fallback and _sentence_count(summary_text) < 2 and _sentence_count(fallback) >= 1:
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
