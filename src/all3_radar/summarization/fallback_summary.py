"""Deterministic fallback summary generation."""

from __future__ import annotations

import re

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")
ELLIPSIS_RE = re.compile(r"\s*(\.\.\.|\u2026|\[\s*\u2026\s*\]|\[\s*\.\.\.\s*\])\s*")
LEADING_PREFIX_PATTERNS = [
    re.compile(r"^\s*insider brief\s*[:.\-]?\s*", re.IGNORECASE),
    re.compile(r"^\s*brief\s*[:.\-]\s*", re.IGNORECASE),
    re.compile(r"^\s*robotics \& automation news\s*[:.\-]\s*", re.IGNORECASE),
    re.compile(r"^\s*the robot report\s*[:.\-]\s*", re.IGNORECASE),
]
BOILERPLATE_PATTERNS = [
    re.compile(r"\bThe post .*? appeared first on .*", re.IGNORECASE),
    re.compile(r"\bRead more\b.*", re.IGNORECASE),
    re.compile(r"\bSubscribe to .*", re.IGNORECASE),
]
LOW_INFORMATION_PATTERNS = [
    re.compile(r"\bdiscusses the future\b", re.IGNORECASE),
    re.compile(r"\bshares insights\b", re.IGNORECASE),
    re.compile(r"\boffers insights\b", re.IGNORECASE),
    re.compile(r"\btakes a look at\b", re.IGNORECASE),
    re.compile(r"\bexplores\b", re.IGNORECASE),
    re.compile(r"\bfuture of\b", re.IGNORECASE),
    re.compile(r"\bhuman-robot interactions\b", re.IGNORECASE),
]
CONCRETE_SUMMARY_TERMS = (
    "funding",
    "raised",
    "investment",
    "partnership",
    "partner",
    "deployment",
    "deploy",
    "pilot",
    "rollout",
    "factory",
    "manufacturing",
    "production",
    "capacity",
    "facility",
    "plant",
    "construction",
    "jobsite",
    "worksite",
    "prefab",
    "modular",
    "off-site",
    "offsite",
    "timber",
    "permit",
    "code",
    "robot",
    "robotics",
    "automation",
    "industrial",
    "launched",
    "launches",
    "unveils",
    "updates",
    "platform",
    "tool",
    "contract",
    "agreement",
)
STRONG_CONCRETE_TERMS = (
    "funding",
    "raised",
    "investment",
    "partnership",
    "deployment",
    "deploy",
    "pilot",
    "rollout",
    "factory",
    "manufacturing",
    "production",
    "capacity",
    "facility",
    "plant",
    "construction",
    "jobsite",
    "worksite",
    "prefab",
    "modular",
    "off-site",
    "offsite",
    "timber",
    "permit",
    "code",
    "launched",
    "launches",
    "unveils",
    "updates",
    "platform",
    "tool",
    "contract",
    "agreement",
)
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
    for pattern in LEADING_PREFIX_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def _has_concrete_signal(sentence: str) -> bool:
    lowered = sentence.lower()
    return bool(re.search(r"\d", lowered)) or any(term in lowered for term in CONCRETE_SUMMARY_TERMS)


def _has_strong_concrete_signal(sentence: str) -> bool:
    lowered = sentence.lower()
    return bool(re.search(r"\d", lowered)) or any(term in lowered for term in STRONG_CONCRETE_TERMS)


def _is_low_information_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if len(lowered.split()) < 6:
        return True
    if lowered.startswith(("this article", "the article", "this piece", "the piece")):
        return True
    return any(pattern.search(lowered) for pattern in LOW_INFORMATION_PATTERNS) and not _has_strong_concrete_signal(lowered)


def remove_repeated_headline(summary: str, headline: str) -> str:
    normalized_summary = summary.strip()
    if normalized_summary.lower().startswith(headline.strip().lower()):
        normalized_summary = normalized_summary[len(headline.strip()) :].lstrip(" .:-")
    return normalized_summary.strip()


def compress_to_two_sentences(summary: str) -> str:
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(summary) if sentence.strip()]
    clean_sentences: list[str] = []
    seen_sentences: set[str] = set()
    for sentence in sentences:
        lowered = sentence.lower()
        if any(marker in lowered for marker in CAPTION_MARKERS):
            continue
        normalized_sentence = WHITESPACE_RE.sub(" ", lowered).strip(" .:-")
        if not normalized_sentence or normalized_sentence in seen_sentences:
            continue
        if _is_low_information_sentence(sentence):
            continue
        seen_sentences.add(normalized_sentence)
        clean_sentences.append(sentence)
    while clean_sentences and clean_sentences[-1][-1] not in ".!?":
        clean_sentences.pop()
    if not clean_sentences:
        return ""
    if not any(_has_concrete_signal(sentence) for sentence in clean_sentences):
        return ""
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
    if "..." in cleaned or "\u2026" in cleaned:
        return None
    if len(cleaned.split()) < 6:
        return None
    if cleaned[-1] not in ".!?":
        return None
    return cleaned


def generate_fallback_summary(headline: str, preview: str | None) -> str | None:
    return sanitize_summary_text(headline, preview)
