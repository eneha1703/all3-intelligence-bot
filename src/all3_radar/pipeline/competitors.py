"""Competitor matching for Bot 1."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from all3_radar.config.loader import load_yaml
from all3_radar.domain.models import CompetitorMatch

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    cleaned = NON_ALNUM_RE.sub(" ", lowered)
    collapsed = WHITESPACE_RE.sub(" ", cleaned).strip()
    return f" {collapsed} " if collapsed else " "


@dataclass(frozen=True)
class CompetitorDefinition:
    canonical: str
    aliases: tuple[str, ...]
    normalized_aliases: tuple[str, ...]


@dataclass(frozen=True)
class CompetitorCatalog:
    companies: tuple[CompetitorDefinition, ...]


def load_competitor_catalog(path: Path) -> CompetitorCatalog:
    payload = load_yaml(path)
    companies = []
    for company in payload.get("companies", []):
        aliases = tuple(str(alias) for alias in company.get("aliases", []))
        all_aliases = (str(company["canonical"]),) + aliases
        companies.append(
            CompetitorDefinition(
                canonical=str(company["canonical"]),
                aliases=all_aliases,
                normalized_aliases=tuple(normalize_match_text(alias).strip() for alias in all_aliases if alias),
            )
        )
    return CompetitorCatalog(companies=tuple(companies))


def detect_competitor_matches(title: str, preview: str | None, catalog: CompetitorCatalog) -> list[CompetitorMatch]:
    fields = {
        "title": normalize_match_text(title),
        "text_preview": normalize_match_text(preview or ""),
    }
    matches: list[CompetitorMatch] = []
    seen: set[tuple[str, str, str]] = set()

    for company in catalog.companies:
        for alias, normalized_alias in zip(company.aliases, company.normalized_aliases):
            if not normalized_alias:
                continue
            needle = f" {normalized_alias} "
            for field_name, haystack in fields.items():
                if needle in haystack:
                    key = (company.canonical, alias, field_name)
                    if key not in seen:
                        matches.append(
                            CompetitorMatch(
                                competitor_name=company.canonical,
                                alias_matched=alias,
                                match_field=field_name,
                            )
                        )
                        seen.add(key)
    return matches
