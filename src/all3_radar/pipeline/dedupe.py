"""Canonical event clustering and direct-vs-wrapper resolution."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from all3_radar.domain.models import ClusterAssignment, StoredNormalizedItem

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "this",
    "that",
    "will",
    "after",
    "amid",
    "over",
    "about",
    "major",
    "new",
    "says",
    "report",
    "reports",
    "launches",
    "launch",
    "announces",
    "announce",
}


@dataclass(frozen=True)
class ClusterableRecord:
    item: StoredNormalizedItem
    source_priority: int
    competitor_count: int
    current_run: bool
    canonical_event_id: str | None = None


@dataclass(frozen=True)
class ClusterResult:
    assignments: dict[str, ClusterAssignment]
    members_by_event_id: dict[str, list[str]]
    published_by_event_id: dict[str, list[datetime | None]]


@dataclass(frozen=True)
class HistoricalCluster:
    records: tuple[ClusterableRecord, ...]
    order: int
    canonical_event_id: str | None = None


def _tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS and len(token) > 2]


def build_event_key(title: str) -> str:
    tokens = _tokenize(title)
    if not tokens:
        return "untitled"
    return "-".join(tokens[:6])


def _is_within_event_window(a: datetime | None, b: datetime | None, days: int = 10) -> bool:
    if a is None or b is None:
        return True
    a_utc = a if a.tzinfo else a.replace(tzinfo=timezone.utc)
    b_utc = b if b.tzinfo else b.replace(tzinfo=timezone.utc)
    return abs(a_utc - b_utc) <= timedelta(days=days)


def _title_similarity(left: str, right: str) -> float:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    containment = max(len(overlap) / len(left_tokens), len(overlap) / len(right_tokens))
    jaccard = len(overlap) / len(union)
    return max(containment, jaccard)


def is_same_event(left: ClusterableRecord, right: ClusterableRecord) -> bool:
    if left.item.canonical_url == right.item.canonical_url:
        return True
    if not _is_within_event_window(left.item.published_ts, right.item.published_ts):
        return False
    left_key = build_event_key(left.item.title)
    right_key = build_event_key(right.item.title)
    if left_key == right_key:
        return True
    return _title_similarity(left.item.title, right.item.title) >= 0.75


def choose_cluster_representative(records: list[ClusterableRecord]) -> ClusterableRecord:
    return sorted(
        records,
        key=lambda record: (
            record.item.layer.value != "direct",
            record.item.is_wrapper,
            -record.item.directness_rank,
            -record.competitor_count,
            -record.source_priority,
            -(1 if record.item.text_preview else 0),
            -len(record.item.title),
            record.item.normalized_item_id,
        ),
    )[0]


def choose_current_run_representative(records: list[ClusterableRecord]) -> ClusterableRecord | None:
    current_records = [record for record in records if record.current_run]
    if not current_records:
        return None
    return choose_cluster_representative(current_records)


def _cluster_current_records(records: list[ClusterableRecord]) -> list[list[ClusterableRecord]]:
    clusters: list[list[ClusterableRecord]] = []
    for record in records:
        matched_cluster = None
        for cluster in clusters:
            if any(is_same_event(record, existing) for existing in cluster):
                matched_cluster = cluster
                break
        if matched_cluster is None:
            clusters.append([record])
        else:
            matched_cluster.append(record)
    return clusters


def _group_historical_records(records: list[ClusterableRecord]) -> list[HistoricalCluster]:
    grouped_records: dict[str, list[ClusterableRecord]] = {}
    grouped_order: dict[str, int] = {}
    ungrouped_clusters: list[HistoricalCluster] = []

    for order, record in enumerate(records):
        if record.canonical_event_id:
            grouped_records.setdefault(record.canonical_event_id, []).append(record)
            grouped_order.setdefault(record.canonical_event_id, order)
            continue
        ungrouped_clusters.append(
            HistoricalCluster(records=(record,), order=order, canonical_event_id=None)
        )

    grouped_clusters = [
        HistoricalCluster(
            records=tuple(grouped_records[event_id]),
            order=grouped_order[event_id],
            canonical_event_id=event_id,
        )
        for event_id in grouped_records
    ]
    return sorted([*grouped_clusters, *ungrouped_clusters], key=lambda cluster: cluster.order)


def _matches_historical_cluster(
    current_cluster: list[ClusterableRecord],
    historical_cluster: HistoricalCluster,
) -> bool:
    return any(
        is_same_event(current_record, historical_record)
        for current_record in current_cluster
        for historical_record in historical_cluster.records
    )


def cluster_records(
    current_records: list[ClusterableRecord],
    historical_records: list[ClusterableRecord],
) -> ClusterResult:
    current_clusters = _cluster_current_records(current_records)
    historical_clusters = _group_historical_records(historical_records)
    matched_current_by_historical_order: dict[int, list[ClusterableRecord]] = defaultdict(list)
    unmatched_current_clusters: list[list[ClusterableRecord]] = []

    for current_cluster in current_clusters:
        matched_historical_order = None
        for historical_cluster in historical_clusters:
            if _matches_historical_cluster(current_cluster, historical_cluster):
                matched_historical_order = historical_cluster.order
                break
        if matched_historical_order is None:
            unmatched_current_clusters.append(current_cluster)
        else:
            matched_current_by_historical_order[matched_historical_order].extend(current_cluster)

    clusters: list[list[ClusterableRecord]] = []
    for historical_cluster in historical_clusters:
        matched_current_records = matched_current_by_historical_order.get(historical_cluster.order, [])
        if not matched_current_records:
            continue
        clusters.append([*historical_cluster.records, *matched_current_records])
    clusters.extend(unmatched_current_clusters)

    assignments: dict[str, ClusterAssignment] = {}
    members_by_event_id: dict[str, list[str]] = defaultdict(list)
    published_by_event_id: dict[str, list[datetime | None]] = defaultdict(list)
    for cluster in clusters:
        cluster_representative = choose_cluster_representative(cluster)
        current_representative = choose_current_run_representative(cluster)
        existing_canonical_event_id = next(
            (record.canonical_event_id for record in cluster if record.canonical_event_id),
            None,
        )
        cluster_event_id = (
            existing_canonical_event_id
            or cluster_representative.canonical_event_id
            or (current_representative.canonical_event_id if current_representative else None)
        )
        cluster_event_id = cluster_event_id or uuid.uuid4().hex
        cluster_title = cluster_representative.item.title
        event_key = build_event_key(cluster_title)
        members_by_event_id[cluster_event_id].extend(record.item.normalized_item_id for record in cluster)
        published_by_event_id[cluster_event_id].extend(record.item.published_ts for record in cluster)

        for record in cluster:
            if not record.current_run:
                continue
            is_cluster_rep = record.item.normalized_item_id == cluster_representative.item.normalized_item_id
            is_current_rep = current_representative is not None and (
                record.item.normalized_item_id == current_representative.item.normalized_item_id
            )
            assignments[record.item.normalized_item_id] = ClusterAssignment(
                canonical_event_id=cluster_event_id,
                event_key=event_key,
                cluster_title=cluster_title,
                is_cluster_representative=is_cluster_rep,
                is_current_run_representative=is_current_rep,
                duplicate_reason=None if is_current_rep else "duplicate_canonical_event",
                representative_item_id=cluster_representative.item.normalized_item_id,
            )
    return ClusterResult(
        assignments=assignments,
        members_by_event_id=dict(members_by_event_id),
        published_by_event_id=dict(published_by_event_id),
    )
