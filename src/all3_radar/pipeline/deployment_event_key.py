"""Conservative semantic key extraction for deployment and rollout events."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

ENTITY_RE = r"[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}"
DEPLOYMENT_PAIR_RE = re.compile(
    rf"(?P<left>{ENTITY_RE})\s+and\s+(?P<right>{ENTITY_RE})\s+"
    r"(?:(?i:to)\s+)?"
    r"(?:(?i:plan|plans|planned)\s+to\s+)?"
    r"(?P<event>(?i:deploy|deploys|deployed|deploying|install|installs|installed|installation|rollout|roll out|rolling out|pilot))\b"
)
LEADING_DEPLOYER_RE = re.compile(
    rf"^(?P<entity>{ENTITY_RE})\s+"
    r"(?:(?i:plan|plans|planned)\s+to\s+)?"
    r"(?P<event>(?i:deploy|deploys|deployed|deploying|install|installs|installed|installation|rollout|roll out|rolling out|pilot))\b"
)
QUANTITY_RE = re.compile(
    r"\b(?P<quantity>\d{1,3}(?:,\d{3})+|\d+)\s+"
    r"(?=(?:[A-Z][A-Za-z0-9&/\-]*\s+){0,3}(?:humanoids?|robots?|robot\s+systems?))",
)
BRANDED_PROGRAM_RE = re.compile(
    r"\b(?P<token>[A-Z][A-Za-z0-9&/\-]*(?:\s+[A-Z0-9][A-Za-z0-9&/\-]*){0,2}\s+"
    r"(?:humanoids?|robots?|robot\s+systems?))\b"
)
GENERIC_PROGRAM_RE = re.compile(
    r"\b(?P<token>humanoids?|robots?|robot\s+systems?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeploymentSemanticKey:
    entity_pair: tuple[str, str] | None
    primary_entity: str | None
    quantity: str | None
    product_token: str | None
    published_date: date


def deployment_key_from_text(
    title: str,
    preview: str | None,
    published_ts: datetime | None,
    event_flags: Mapping[str, object],
) -> DeploymentSemanticKey | None:
    if not bool(event_flags.get("deployment_event")):
        return None
    if published_ts is None:
        return None

    text = f"{title} {preview or ''}".strip()
    primary_entity = _extract_primary_entity(title)
    product_token = _extract_strong_program_token(text)
    quantity = _extract_quantity(text)
    entity_pair = _extract_entity_pair(text, primary_entity, product_token)
    if product_token and entity_pair and _is_entity_branded_generic_token(product_token, entity_pair):
        product_token = None

    if entity_pair is None and primary_entity is None:
        return None
    if quantity is None and product_token is None:
        return None
    if entity_pair is None and product_token is None:
        return None

    return DeploymentSemanticKey(
        entity_pair=entity_pair,
        primary_entity=primary_entity,
        quantity=quantity,
        product_token=product_token,
        published_date=published_ts.date(),
    )


def same_deployment_event(
    current: DeploymentSemanticKey,
    previous: DeploymentSemanticKey,
    max_day_delta: int = 7,
) -> bool:
    if abs((current.published_date - previous.published_date).days) > max_day_delta:
        return False

    if current.quantity != previous.quantity:
        return False

    if current.product_token and previous.product_token and current.product_token != previous.product_token:
        return False

    if current.entity_pair and previous.entity_pair:
        return current.entity_pair == previous.entity_pair

    if current.entity_pair or previous.entity_pair:
        pair = current.entity_pair or previous.entity_pair
        solo = current if current.entity_pair is None else previous
        return bool(pair and solo.primary_entity and solo.primary_entity in pair)

    return current.primary_entity == previous.primary_entity


def _extract_primary_entity(title: str) -> str | None:
    match = LEADING_DEPLOYER_RE.search(title)
    if not match:
        return None
    return _normalize_entity(match.group("entity"))


def _extract_entity_pair(text: str, primary_entity: str | None, product_token: str | None) -> tuple[str, str] | None:
    pairs: set[tuple[str, str]] = set()
    for match in DEPLOYMENT_PAIR_RE.finditer(text):
        left = _normalize_entity(match.group("left"))
        right = _normalize_entity(match.group("right"))
        if not left or not right or left == right:
            continue
        pairs.add(tuple(sorted((left, right))))

    if len(pairs) > 1:
        return None
    if len(pairs) == 1:
        return next(iter(pairs))

    if not primary_entity or not product_token:
        return None

    product_brand = _extract_brand_entity_from_program(product_token)
    if not product_brand or product_brand == primary_entity:
        return None
    return tuple(sorted((primary_entity, product_brand)))


def _extract_quantity(text: str) -> str | None:
    match = QUANTITY_RE.search(text)
    if not match:
        return None
    return match.group("quantity").replace(",", "")


def _extract_strong_program_token(text: str) -> str | None:
    branded_tokens = {
        _normalize_program_token(match.group("token"))
        for match in BRANDED_PROGRAM_RE.finditer(text)
        if _normalize_program_token(match.group("token")) is not None
    }
    if len(branded_tokens) == 1:
        return next(iter(branded_tokens))
    if len(branded_tokens) > 1:
        return None

    generic_tokens = {
        _normalize_program_token(match.group("token"))
        for match in GENERIC_PROGRAM_RE.finditer(text)
        if _normalize_program_token(match.group("token")) is not None
    }
    if len(generic_tokens) == 1:
        return next(iter(generic_tokens))
    return None


def _extract_brand_entity_from_program(product_token: str) -> str | None:
    parts = product_token.split()
    if len(parts) < 2:
        return None
    first = parts[0]
    if first in {"humanoid", "humanoids", "robot", "robots"}:
        return None
    return _normalize_entity(first)


def _is_entity_branded_generic_token(product_token: str, entity_pair: tuple[str, str]) -> bool:
    parts = product_token.split()
    if len(parts) < 2:
        return False
    trailing = " ".join(parts[1:])
    if trailing not in {"humanoid", "humanoids", "robot", "robots", "robot systems"}:
        return False
    leading_entity = _normalize_entity(parts[0])
    return leading_entity in entity_pair if leading_entity else False


def _normalize_entity(raw: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", raw).strip().lower()
    if not cleaned or cleaned in {"the", "a", "an", "plan", "plans"}:
        return None
    return re.sub(r"\s+", " ", cleaned)


def _normalize_program_token(raw: str) -> str | None:
    lowered = raw.strip().lower()
    lowered = re.sub(r"[^a-z0-9/\-\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip(" -/")
    if not lowered:
        return None
    if lowered in {"humanoid", "humanoids", "robot", "robots", "robot systems"}:
        return None
    return lowered
