"""Deterministic fallback summary generation."""

from __future__ import annotations

import re

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")
ELLIPSIS_RE = re.compile(r"\s*(\.\.\.|…|\[\s*…\s*\]|\[\s*\.\.\.\s*\])\s*")
BOILERPLATE_PATTERNS = [
    re.compile(r"\bThe post .*? appeared first on .*", re.IGNORECASE),
    re.compile(r"\bRead more\b.*", re.IGNORECASE),
    re.compile(r"\bSubscribe to .*", re.IGNORECASE),
]
CAPTION_MARKERS = (
    "getty images",
    "courtesy of",
    "picture alliance",
    "shutterstock",
    "reuters",
    "associated press",
    "ap photo",
    "zillow",
)


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = WHITESPACE_RE.sub(" ", value).strip()
    return normalized or None


def _strip_boilerplate(text: str) -> str:
    cleaned = text
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def remove_repeated_headline(summary: str, headline: str) -> str:
    normalized_summary = summary.strip()
    if normalized_summary.lower().startswith(headline.strip().lower()):
        normalized_summary = normalized_summary[len(headline.strip()):].lstrip(" .:-")
    return normalized_summary.strip()


def compress_to_two_sentences(summary: str) -> str:
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(summary) if sentence.strip()]
    clean_sentences = [
        sentence
        for sentence in sentences
        if not any(marker in sentence.lower() for marker in CAPTION_MARKERS)
    ]
    while clean_sentences and clean_sentences[-1][-1] not in ".!?":
        clean_sentences.pop()
    return " ".join(clean_sentences[:2])


def sanitize_summary_text(headline: str, summary: str | None) -> str | None:
    cleaned = _clean_text(summary)
    if not cleaned:
        return None
    cleaned = _strip_boilerplate(cleaned)
    cleaned = remove_repeated_headline(cleaned, headline)
    cleaned = ELLIPSIS_RE.split(cleaned)[0].strip()
    cleaned = compress_to_two_sentences(cleaned)
    cleaned = _clean_text(cleaned)
    if not cleaned:
        return None
    if cleaned.endswith(":"):
        return None
    if "..." in cleaned or "…" in cleaned:
        return None
    if len(cleaned.split()) < 6:
        return None
    if cleaned[-1] not in ".!?":
        return None
    return cleaned


def generate_fallback_summary(headline: str, preview: str | None) -> str | None:
    return sanitize_summary_text(headline, preview)
