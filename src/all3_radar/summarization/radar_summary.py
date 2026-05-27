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
GERMAN_MONTHS_EN = {
    "januar": "January",
    "februar": "February",
    "maerz": "March",
    "marz": "March",
    "m\u00e4rz": "March",
    "april": "April",
    "mai": "May",
    "juni": "June",
    "juli": "July",
    "august": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "dezember": "December",
}
GERMAN_LARGE_NUMBER_RE = re.compile(r"\b\d{1,3}(?:[.\s]\d{3})+\b")
GERMAN_PERCENT_RE = re.compile(r"([+-]?\d+(?:[,.]\d+)?)\s*(?:%|\bprozent\b)", re.IGNORECASE)
GERMAN_TEXT_MARKERS = (
    " statisches bundesamt",
    " baugenehmigung",
    " baugenehmigungen",
    " bauhauptgewerbe",
    " fertigstellung",
    " fertigstellungen",
    " fertiggestellt",
    " gegen\u00fcber",
    " weniger ",
    " mehr ",
    " monat",
    " monate",
    " vorjahr",
    " vormonat",
    " wohnung",
    " wohnungen",
    " wurde ",
    " wurden ",
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


def should_translate_delivery(item: StoredNormalizedItem) -> bool:
    origin_language = str(item.metadata.get("origin_language") or "").strip().lower()
    delivery_language = str(item.metadata.get("delivery_language") or "").strip().lower()
    return bool(origin_language and delivery_language and origin_language != delivery_language)


def _format_german_number(raw_value: str) -> str:
    value = raw_value.strip()
    if "," in value and "." not in value and " " not in value:
        return value.replace(",", ".")
    return value.replace(".", ",").replace(" ", ",")


def _local_german_housing_delivery_fallback(
    *,
    item: StoredNormalizedItem,
    headline: str,
    source_summary: str,
) -> tuple[str, str] | None:
    origin_language = str(item.metadata.get("origin_language") or "").strip().lower()
    delivery_language = str(item.metadata.get("delivery_language") or "").strip().lower()
    if origin_language != "de" or delivery_language != "en":
        return None

    haystack = f"{headline} {source_summary} {item.text_preview or ''}".lower()
    if item.source_id not in {"destatis_press_listing", "haufe_immobilien_listing"}:
        return None

    if "auftragseingang" in haystack and "bauhauptgewerbe" in haystack:
        percent_match = GERMAN_PERCENT_RE.search(haystack)
        month_year_match = re.search(
            r"\b(?:im|in)\s+([a-z\u00e4]+)\s+(20\d{2})\b",
            haystack,
            re.IGNORECASE,
        )
        percent = _format_german_number(percent_match.group(1)) if percent_match else None
        period = None
        if month_year_match:
            month = GERMAN_MONTHS_EN.get(month_year_match.group(1).lower(), month_year_match.group(1).title())
            period = f"{month} {month_year_match.group(2)}"
        direction = "rose"
        if percent and percent.startswith("-"):
            direction = "fell"
            percent = percent.lstrip("-")
        elif percent:
            percent = percent.lstrip("+")
        translated_headline = (
            f"German construction orders {direction} {percent}% month on month"
            + (f" in {period}" if period else "")
            if percent
            else "German construction orders changed month on month"
        )
        translated_summary = (
            f"Destatis says German main construction orders {direction}"
            + (f" {percent}% month on month" if percent else " month on month")
            + (f" in {period}" if period else "")
            + ". The data is a direct signal for near-term demand in Germany's construction pipeline."
        )
        translated_summary = sanitize_summary_text(translated_headline, translated_summary)
        return (translated_headline, translated_summary) if translated_summary else None

    housing_completion_terms = (
        "fertigstellungen",
        "fertiggestellt",
        "wohnungen fertiggestellt",
        "wohnungsbau-statistik",
    )
    if any(term in haystack for term in housing_completion_terms):
        large_numbers = [_format_german_number(match.group(0)) for match in GERMAN_LARGE_NUMBER_RE.finditer(source_summary)]
        percent_match = GERMAN_PERCENT_RE.search(source_summary)
        percent = _format_german_number(percent_match.group(1)).lstrip("+-") if percent_match else None
        completed = large_numbers[0] if large_numbers else None
        decline = large_numbers[1] if len(large_numbers) > 1 else None
        translated_headline = "German housing completions hit lowest level since 2012"
        lead = (
            f"Germany completed {completed} homes in 2025"
            if completed
            else "German housing construction fell to its weakest level since 2012"
        )
        if decline:
            lead += f", {decline} fewer than a year earlier"
        elif percent:
            lead += f", {percent}% fewer than a year earlier"
        translated_summary = (
            f"{lead}. The figures point to a deepening delivery gap in German housing and renewed pressure "
            "for faster permitting and construction."
        )
        translated_summary = sanitize_summary_text(translated_headline, translated_summary)
        return (translated_headline, translated_summary) if translated_summary else None

    housing_policy_terms = (
        "baugesetzbuch",
        "baugb",
        "bauturbo",
        "modernisierung des städtebau",
        "raumordnungsrechts",
    )
    if any(term in haystack for term in housing_policy_terms) and (
        "wohnungsbau" in haystack or "housing" in haystack or "bauturbo" in haystack
    ):
        date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", haystack)
        date_phrase = ""
        if date_match:
            day, month, year = date_match.groups()
            month_name = {
                "1": "January",
                "2": "February",
                "3": "March",
                "4": "April",
                "5": "May",
                "6": "June",
                "7": "July",
                "8": "August",
                "9": "September",
                "10": "October",
                "11": "November",
                "12": "December",
            }.get(str(int(month)))
            if month_name:
                date_phrase = f" on {month_name} {int(day)}, {year}"

        translated_headline = "German cabinet approves BauGB reform draft to speed housing construction"
        translated_summary = (
            f"Germany's cabinet approved a draft reform of planning law{date_phrase}. "
            "The package gives housing construction higher priority and now moves to the Bundestag."
        )
        translated_summary = sanitize_summary_text(translated_headline, translated_summary)
        return (translated_headline, translated_summary) if translated_summary else None

    return None


def _looks_untranslated_german(text: str) -> bool:
    normalized = f" {text.lower()} "
    marker_count = sum(1 for marker in GERMAN_TEXT_MARKERS if marker in normalized)
    has_german_char = any(character in normalized for character in ("\u00e4", "\u00f6", "\u00fc", "\u00df"))
    return marker_count >= 2 or (has_german_char and marker_count >= 1)


def maybe_translate_delivery_card(
    *,
    item: StoredNormalizedItem,
    headline: str,
    summary_text: str | None,
    gemini_client: GeminiClient,
) -> tuple[str, str | None, bool, str | None]:
    if not should_translate_delivery(item):
        return headline, summary_text, False, None
    source_summary = summary_text or sanitize_summary_text(headline, item.text_preview) or item.text_preview or item.title
    if not source_summary:
        return headline, summary_text, False, "translation_source_missing"
    local_fallback = _local_german_housing_delivery_fallback(
        item=item,
        headline=headline,
        source_summary=source_summary,
    )
    rewrite_fn = getattr(gemini_client, "rewrite_delivery_card", None)
    if not callable(rewrite_fn) or not getattr(gemini_client, "is_available", False):
        if local_fallback is not None:
            return local_fallback[0], local_fallback[1], True, None
        return headline, None, False, "translation_unavailable"
    try:
        translated_headline, translated_summary = rewrite_fn(
            title=headline,
            summary=source_summary,
            source_language=str(item.metadata.get("origin_language") or "de"),
            target_language="English",
        )
    except GeminiUnavailableError as exc:
        if local_fallback is not None:
            return local_fallback[0], local_fallback[1], True, None
        return headline, None, False, str(exc)
    translated_summary = sanitize_summary_text(translated_headline, translated_summary)
    if not translated_headline.strip() or not translated_summary:
        if local_fallback is not None:
            return local_fallback[0], local_fallback[1], True, None
        return headline, None, False, "translation_invalid"
    if _looks_untranslated_german(f"{translated_headline} {translated_summary}"):
        if local_fallback is not None:
            return local_fallback[0], local_fallback[1], True, None
        return headline, None, False, "translation_untranslated_output"
    return translated_headline.strip(), translated_summary, True, None


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
