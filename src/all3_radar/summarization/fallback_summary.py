"""Deterministic fallback summary generation."""

from __future__ import annotations

import re

MAX_SUMMARY_SENTENCES = 3
MAX_SENTENCE_WORDS = 28
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
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
    "customer",
    "site",
    "factory floor",
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
    "customer",
    "site",
    "factory floor",
)
CLAUSE_TRIM_MARKERS = (
    ", creating ",
    ", where ",
    ", which ",
    ", enabling ",
    ", allowing ",
    ", providing ",
    ", helping ",
    ", describing ",
    " while ",
)
TRAILING_FRAGMENT_PATTERNS = [
    re.compile(r",?\s*according(?:\s+to.*)?\.?$", re.IGNORECASE),
    re.compile(r",?\s*including\.?$", re.IGNORECASE),
    re.compile(r",?\s*such as\.?$", re.IGNORECASE),
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
SIMILARITY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "this",
    "that",
    "its",
    "their",
    "his",
    "her",
    "our",
    "your",
    "has",
    "have",
    "had",
    "are",
    "is",
    "was",
    "were",
    "will",
    "new",
    "said",
}


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = WHITESPACE_RE.sub(" ", value).strip()
    return normalized or None


def _sentence_count(text: str | None) -> int:
    if not text:
        return 0
    return len([sentence for sentence in SENTENCE_SPLIT_RE.split(text) if sentence.strip()])


def _tokenize_for_similarity(text: str) -> set[str]:
    return {
        token
        for token in TOKEN_RE.findall(text.lower())
        if len(token) > 2 and token not in SIMILARITY_STOPWORDS
    }


def _is_similar_sentence(left: str, right: str) -> bool:
    left_tokens = _tokenize_for_similarity(left)
    right_tokens = _tokenize_for_similarity(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return (len(overlap) / len(left_tokens) >= 0.75) or (len(overlap) / len(right_tokens) >= 0.75)


def _subject_auxiliaries(subject: str) -> tuple[str, str, str]:
    plural = " and " in subject.lower()
    return (
        "have" if plural else "has",
        "are" if plural else "is",
        "their" if plural else "its",
    )


def _match_title_pattern(headline: str) -> tuple[str, str, str] | None:
    cleaned = _clean_text(headline)
    if not cleaned:
        return None

    patterns = (
        (re.compile(r"^(?P<subject>.+?) announces (?P<object>.+)$", re.IGNORECASE), "announces"),
        (re.compile(r"^(?P<subject>.+?) launches (?P<object>.+)$", re.IGNORECASE), "launches"),
        (re.compile(r"^(?P<subject>.+?) breaks ground on (?P<object>.+)$", re.IGNORECASE), "breaks_ground"),
        (re.compile(r"^(?P<subject>.+?) partner[s]? with (?P<object>.+)$", re.IGNORECASE), "partners_with"),
        (re.compile(r"^(?P<subject>.+?) partner[s]? for (?P<object>.+)$", re.IGNORECASE), "partners_for"),
        (re.compile(r"^(?P<subject>.+?) expand[s]? partnership to (?P<object>.+)$", re.IGNORECASE), "expands_partnership"),
        (re.compile(r"^(?P<subject>.+?) raise[s]? (?P<object>.+)$", re.IGNORECASE), "raises"),
        (re.compile(r"^(?P<subject>.+?) open[s]? (?P<object>.+)$", re.IGNORECASE), "opens"),
    )

    for pattern, kind in patterns:
        match = pattern.match(cleaned)
        if not match:
            continue
        return match.group("subject").strip(), match.group("object").strip().rstrip("."), kind
    return None


def _compose_title_sentence(headline: str) -> str | None:
    matched = _match_title_pattern(headline)
    if not matched:
        return None

    subject, obj, kind = matched
    have, be, possessive = _subject_auxiliaries(subject)
    if kind == "announces":
        return f"{subject} {have} announced {obj}."
    if kind == "launches":
        return f"{subject} {have} launched {obj}."
    if kind == "breaks_ground":
        return f"{subject} {have} broken ground on {obj}."
    if kind == "partners_with":
        return f"{subject} {have} partnered with {obj}."
    if kind == "partners_for":
        return f"{subject} {have} partnered for {obj}."
    if kind == "expands_partnership":
        return f"{subject} {be} expanding {possessive} partnership to {obj}."
    if kind == "raises":
        return f"{subject} {have} raised {obj}."
    if kind == "opens":
        return f"{subject} {have} opened {obj}."
    return None


def _single_sentence_preview_duplicates_announce_headline(headline: str, preview_sentence: str) -> bool:
    matched = _match_title_pattern(headline)
    if not matched:
        return False
    subject, _, kind = matched
    if kind != "announces":
        return False
    lowered_preview = preview_sentence.lower().strip()
    return lowered_preview.startswith(subject.lower())


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


def _ensure_terminal_punctuation(sentence: str) -> str:
    stripped = sentence.strip()
    if not stripped:
        return ""
    if stripped[-1] in ".!?":
        return stripped
    return f"{stripped}."


def _cleanup_trailing_fragment(sentence: str) -> str:
    cleaned = sentence.strip()
    for pattern in TRAILING_FRAGMENT_PATTERNS:
        cleaned = pattern.sub("", cleaned).rstrip(" ,;:-")
    return cleaned


def _trim_long_sentence(sentence: str) -> str:
    normalized = WHITESPACE_RE.sub(" ", sentence).strip()
    if len(normalized.split()) <= MAX_SENTENCE_WORDS:
        return _ensure_terminal_punctuation(_cleanup_trailing_fragment(normalized))

    lowered = normalized.lower()
    for marker in CLAUSE_TRIM_MARKERS:
        index = lowered.find(marker)
        if index > 0:
            candidate = normalized[:index].rstrip(" ,;:-")
            if len(candidate.split()) >= 7 and _has_concrete_signal(candidate):
                return _ensure_terminal_punctuation(_cleanup_trailing_fragment(candidate))

    comma_index = normalized.find(",")
    if comma_index > 0:
        candidate = normalized[:comma_index].rstrip(" ,;:-")
        if len(candidate.split()) >= 7 and _has_concrete_signal(candidate):
            return _ensure_terminal_punctuation(_cleanup_trailing_fragment(candidate))

    words = normalized.split()
    trimmed_words = words[:MAX_SENTENCE_WORDS]
    candidate = " ".join(trimmed_words).rstrip(" ,;:-")
    return _ensure_terminal_punctuation(_cleanup_trailing_fragment(candidate))


def remove_repeated_headline(summary: str, headline: str) -> str:
    normalized_summary = summary.strip()
    if normalized_summary.lower().startswith(headline.strip().lower()):
        normalized_summary = normalized_summary[len(headline.strip()) :].lstrip(" .:-")
    return normalized_summary.strip()


def compress_to_digest_sentences(summary: str) -> str:
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(summary) if sentence.strip()]
    clean_sentences: list[str] = []
    seen_sentences: set[str] = set()
    for sentence in sentences:
        lowered = sentence.lower()
        if any(marker in lowered for marker in CAPTION_MARKERS):
            continue
        trimmed_sentence = _trim_long_sentence(sentence)
        normalized_sentence = WHITESPACE_RE.sub(" ", trimmed_sentence.lower()).strip(" .:-")
        if not normalized_sentence or normalized_sentence in seen_sentences:
            continue
        if _is_low_information_sentence(trimmed_sentence):
            continue
        seen_sentences.add(normalized_sentence)
        clean_sentences.append(trimmed_sentence)

    if not clean_sentences:
        return ""
    if not any(_has_concrete_signal(sentence) for sentence in clean_sentences):
        return ""
    return " ".join(clean_sentences[:MAX_SUMMARY_SENTENCES])


def sanitize_summary_text(headline: str, summary: str | None) -> str | None:
    cleaned = _clean_text(summary)
    if not cleaned:
        return None
    had_ellipsis = bool(ELLIPSIS_RE.search(cleaned))
    cleaned = _strip_boilerplate(cleaned)
    cleaned = remove_repeated_headline(cleaned, headline)
    cleaned = ELLIPSIS_RE.split(cleaned)[0].strip()
    cleaned = compress_to_digest_sentences(cleaned)
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
    if had_ellipsis:
        if _sentence_count(cleaned) < 2:
            return None
    return cleaned


def generate_fallback_summary(headline: str, preview: str | None) -> str | None:
    preview_summary = sanitize_summary_text(headline, preview)
    if preview_summary and _sentence_count(preview_summary) >= 2:
        return preview_summary

    title_sentence = _compose_title_sentence(headline)
    if title_sentence and preview_summary:
        preview_sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(preview_summary) if sentence.strip()]
        if (
            len(preview_sentences) == 1
            and _single_sentence_preview_duplicates_announce_headline(headline, preview_sentences[0])
        ):
            return sanitize_summary_text(headline, title_sentence)
        if preview_sentences and not _is_similar_sentence(title_sentence, preview_sentences[0]):
            composed = " ".join([title_sentence, *preview_sentences[:2]])
            return sanitize_summary_text(headline, composed)

    if preview_summary:
        return preview_summary
    if title_sentence:
        return sanitize_summary_text(headline, title_sentence)
    return None
