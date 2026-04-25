"""Deterministic fallback summary generation."""

from __future__ import annotations

import re

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = WHITESPACE_RE.sub(" ", value).strip()
    return normalized or None


def remove_repeated_headline(summary: str, headline: str) -> str:
    normalized_summary = summary.strip()
    if normalized_summary.lower().startswith(headline.strip().lower()):
        normalized_summary = normalized_summary[len(headline.strip()):].lstrip(" .:-")
    return normalized_summary.strip()


def compress_to_two_sentences(summary: str) -> str:
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(summary) if sentence.strip()]
    return " ".join(sentences[:2])


def generate_fallback_summary(headline: str, preview: str | None) -> str | None:
    cleaned_preview = _clean_text(preview)
    if cleaned_preview:
        cleaned_preview = remove_repeated_headline(cleaned_preview, headline)
        cleaned_preview = compress_to_two_sentences(cleaned_preview)
        if cleaned_preview:
            return cleaned_preview

    stripped_headline = headline.strip().rstrip(".")
    if not stripped_headline:
        return None
    return f"The article reports {stripped_headline[0].lower() + stripped_headline[1:]}."
