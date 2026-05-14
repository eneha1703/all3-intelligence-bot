"""End-to-end weekly digest build service."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from all3_radar.config.loader import load_settings
from all3_radar.digest.claude_client import ClaudeDigestClient, ClaudeDigestUnavailableError
from all3_radar.digest.corpus import (
    DigestCandidate,
    build_claude_selection_prompt,
    build_claude_writer_prompt,
    build_default_output_path,
    hydrate_digest_candidates,
    resolve_digest_window,
)
from all3_radar.digest.writer import build_digest_html, build_digest_markdown
from all3_radar.domain.enums import PipelineName, PipelineStatus
from all3_radar.observability.logging import configure_logging
from all3_radar.pipeline.funding_sent_history import funding_key_from_text
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository

LOGGER = logging.getLogger(__name__)
WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
WEEKLY_PREFERRED_BUCKETS = (
    "physical_ai_proof",
    "mass_timber_construction",
    "strategic_capital_bet",
    "infrastructure_platform_signal",
    "construction_robotics",
)
WEEKLY_BUCKET_RANK = {
    "physical_ai_proof": 0,
    "mass_timber_construction": 1,
    "strategic_capital_bet": 2,
    "infrastructure_platform_signal": 3,
    "construction_robotics": 4,
    "construction_statistics": 5,
    "industrial_deployment": 6,
    "general_relevant": 7,
    "timber_supply_chain": 8,
    "weak_generic_funding": 9,
    "weak_off_thesis": 10,
}


@dataclass(frozen=True)
class WeeklyDigestBuildResult:
    pipeline_run_id: str
    digest_run_id: str
    week_key: str
    output_path: Path
    candidate_count: int
    claude_used: bool
    fallback_reason: str | None


@dataclass(frozen=True)
class WeeklyDigestShortlistResult:
    pipeline_run_id: str
    digest_run_id: str
    week_key: str
    candidate_count: int
    candidates: list[DigestCandidate]


def _settings_snapshot(settings: object) -> dict:
    snapshot = asdict(settings)
    snapshot["app"]["database_path"] = str(snapshot["app"]["database_path"])
    snapshot["integrations"]["gemini_api_key"] = "***" if snapshot["integrations"]["gemini_api_key"] else None
    snapshot["integrations"]["anthropic_api_key"] = "***" if snapshot["integrations"]["anthropic_api_key"] else None
    snapshot["integrations"]["telegram_alert_bot_token"] = (
        "***" if snapshot["integrations"]["telegram_alert_bot_token"] else None
    )
    return snapshot


def _normalize_digest_title(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip().lower()


def _normalize_digest_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = NON_ALNUM_RE.sub(" ", value.lower())
    return WHITESPACE_RE.sub(" ", normalized).strip()


def _has_any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _row_signal_score(row: dict[str, object]) -> int:
    try:
        signals = json.loads(str(row.get("signals_json") or "{}"))
    except json.JSONDecodeError:
        return 0
    event_flags = signals.get("event_flags", {}) if isinstance(signals, dict) else {}
    if not isinstance(event_flags, dict):
        return 0
    weighted_flags = (
        "industrial_robotics_signal",
        "construction_innovation_signal",
        "timber_strategic_signal",
        "construction_statistics_signal",
        "deployment_event",
        "partnership_event",
        "funding_event",
    )
    return sum(1 for key in weighted_flags if event_flags.get(key))


def _row_event_flags(row: dict[str, object]) -> dict[str, object]:
    try:
        signals = json.loads(str(row.get("signals_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    event_flags = signals.get("event_flags", {}) if isinstance(signals, dict) else {}
    return event_flags if isinstance(event_flags, dict) else {}


def _row_funding_identity(row: dict[str, object]) -> str | None:
    published_ts_raw = row.get("published_ts")
    if not published_ts_raw:
        return None
    try:
        published_ts = datetime.fromisoformat(str(published_ts_raw))
    except ValueError:
        return None
    semantic_key = funding_key_from_text(
        title=str(row.get("title") or ""),
        preview=str(row.get("summary_text") or ""),
        published_ts=published_ts,
        event_flags=_row_event_flags(row),
    )
    if semantic_key is None:
        return None
    currency, value, scale = semantic_key.amount
    round_marker = (semantic_key.round_marker or "").replace(" round", "")
    return f"funding:{semantic_key.entity}|{currency}{value}{scale}|{round_marker}"


def _is_obvious_weekly_noise(row: dict[str, object]) -> bool:
    title = _normalize_digest_text(str(row.get("title") or ""))
    summary = _normalize_digest_text(str(row.get("summary_text") or ""))
    combined = f"{title} {summary}".strip()
    if not combined:
        return False

    if (
        "waymo" in combined
        and ("how to ride" in combined or "crash record" in combined or "robotaxi service" in combined)
    ):
        return True

    if any(
        phrase in combined
        for phrase in (
            "chefs share",
            "menu changes",
            "event logistics",
            "solo cooking companies",
            "social strategy",
        )
    ):
        return True

    if any(
        phrase in combined
        for phrase in (
            "documentary filmmaker",
            "founder documentary",
            "behind the scenes doc",
            "social media video blitz",
            "launch video",
            "robo housemaid",
            "consumer robotics startup",
            "starts shipping this summer",
        )
    ):
        return True

    if any(
        phrase in combined
        for phrase in (
            "tracks ai use",
            "internal friction",
            "employees push back",
            "engineers use ai",
            "parts of its workforce",
        )
    ):
        return True

    if any(
        phrase in combined
        for phrase in (
            "want to hire",
            "talent pool",
            "industry night",
            "autonomous vehicle industry is ripe for picking",
            "experience transfers well",
            "startup CEOs told Business Insider",
        )
    ):
        return True

    return False


def _is_ineligible_weekly_candidate(row: dict[str, object]) -> bool:
    skip_reason = str(row.get("skip_reason") or "")
    if skip_reason in {
        "claude_editorial_rejected",
        "editorial_not_telegram_worthy",
        "editorial_thought_leadership_without_operational_signal",
    }:
        return True

    flags = _row_event_flags(row)
    if bool(flags.get("adjacent_logistics_only", False)):
        return True

    return False


def _weekly_bucket(row: dict[str, object]) -> str:
    title = _normalize_digest_text(str(row.get("title") or ""))
    summary = _normalize_digest_text(str(row.get("summary_text") or ""))
    combined = f"{title} {summary}".strip()
    flags = _row_event_flags(row)

    if _has_any_phrase(
        combined,
        (
            "marine terminal",
            "portland marine terminal",
            "distribution hub",
            "production and distribution hub",
            "one stop shop",
            "timber supply",
            "mass timber supply",
            "former terminal",
            "willamette river",
        ),
    ):
        return "timber_supply_chain"

    if _has_any_phrase(
        combined,
        (
            "in space drug manufacturing",
            "drug manufacturing company",
            "cancer drugs in orbit",
            "in space manufacturing",
            "drugs in orbit",
        ),
    ):
        return "weak_off_thesis"

    if (
        bool(flags.get("timber_strategic_signal"))
        or "mass timber" in combined
        or _has_any_phrase(combined, ("clt", "lvl posts", "lvl beams", "urban sites", "tight city plot"))
    ) and _has_any_phrase(
        combined,
        (
            "building",
            "office building",
            "school",
            "project",
            "construction",
            "urban",
            "site",
            "concrete sidewalls",
            "three storey office",
        ),
    ):
        return "mass_timber_construction"

    if _has_any_phrase(
        combined,
        (
            "construction robotics",
            "robotic construction",
            "off site robotic fabrication",
            "on site assembly",
            "autonomous building platform",
            "housing industrialization",
            "ai assisted design",
        ),
    ):
        return "construction_robotics"

    if bool(flags.get("industrial_robotics_signal")) and _has_any_phrase(
        combined,
        (
            "systems live",
            "production picks",
            "remote human intervention",
            "reliability",
            "warehouse production metrics",
            "production proof",
            "scaled manufacturing operations",
            "production lines",
            "8 hour shifts",
            "full factory style",
            "factory style",
            "without intervention",
            "full shift",
            "entire shift",
        ),
    ):
        return "physical_ai_proof"

    if _has_any_phrase(
        combined,
        (
            "softbank",
            "roze",
            "abb robotics",
            "data center buildout",
            "data center growth",
            "energy land and infrastructure",
            "physical delivery problem",
        ),
    ):
        return "infrastructure_platform_signal"

    if bool(flags.get("funding_event")) and _has_any_phrase(
        combined,
        (
            "valuation",
            "total funding",
            "platform opportunity",
            "physical industries",
            "advanced manufacturing",
            "aerospace",
            "automotive",
            "drug discovery",
            "project prometheus",
        ),
    ):
        return "strategic_capital_bet"

    if bool(flags.get("construction_statistics_signal")):
        return "construction_statistics"

    if bool(flags.get("industrial_robotics_signal")) or bool(flags.get("deployment_event")):
        if _has_any_phrase(combined, ("deploy", "deployment", "humanoids by 2032", "manufacturing facilities")):
            return "industrial_deployment"

    if bool(flags.get("funding_event")) and _has_any_phrase(
        combined,
        (
            "venture arm",
            "venture capital arm",
            "fund iii",
            "independent venture capital arm",
            "launched its third fund",
            "bet on physical ai and robotics",
        ),
    ):
        return "weak_generic_funding"

    return "general_relevant"


def _sort_digest_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            WEEKLY_BUCKET_RANK.get(_weekly_bucket(row), 50),
            0 if str(row.get("send_status") or "") == "sent" else 1,
            -_row_signal_score(row),
            -int(row.get("score") or 0),
            str(row.get("canonical_event_id") or ""),
        ),
    )


def _dedupe_semantic_digest_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for row in rows:
        funding_key = _row_funding_identity(row)
        if funding_key and funding_key in seen_keys:
            continue
        deduped.append(row)
        if funding_key:
            seen_keys.add(funding_key)
    return deduped


def _prepare_digest_rows(rows: list[dict[str, object]], *, limit: int) -> list[dict[str, object]]:
    rows = [row for row in rows if not _is_ineligible_weekly_candidate(row)]
    manual_rows = _dedupe_semantic_digest_rows(
        _sort_digest_rows([row for row in rows if bool(row.get("manual_shortlist_signal"))])
    )
    selected_ids = {str(row["canonical_event_id"]) for row in manual_rows}
    prepared: list[dict[str, object]] = list(manual_rows)
    if len(prepared) >= limit:
        return prepared[:limit]

    remaining_rows = [row for row in rows if str(row["canonical_event_id"]) not in selected_ids]
    non_noise_rows = [row for row in rows if not _is_obvious_weekly_noise(row)]
    non_noise_rows = [row for row in non_noise_rows if str(row["canonical_event_id"]) not in selected_ids]
    strong_rows = [
        row for row in non_noise_rows if _weekly_bucket(row) not in {"weak_generic_funding", "weak_off_thesis"}
    ]
    sent_strong_rows = [row for row in strong_rows if str(row.get("send_status") or "") == "sent"]
    stored_strong_rows = [row for row in strong_rows if str(row.get("send_status") or "") != "sent"]

    sorted_sent_rows = _dedupe_semantic_digest_rows(_sort_digest_rows(sent_strong_rows))
    sorted_stored_rows = _dedupe_semantic_digest_rows(_sort_digest_rows(stored_strong_rows))

    preferred: list[dict[str, object]] = []
    for bucket in WEEKLY_PREFERRED_BUCKETS:
        for pool in (sorted_sent_rows, sorted_stored_rows):
            for row in pool:
                row_id = str(row["canonical_event_id"])
                if row_id in selected_ids or _weekly_bucket(row) != bucket:
                    continue
                preferred.append(row)
                selected_ids.add(row_id)
                break
            else:
                continue
            break

    remaining_sent_rows = [row for row in sorted_sent_rows if str(row["canonical_event_id"]) not in selected_ids]
    prepared.extend(preferred + remaining_sent_rows)
    if len(prepared) >= min(limit, 5):
        return prepared[:limit]

    remaining_stored_rows = [row for row in sorted_stored_rows if str(row["canonical_event_id"]) not in selected_ids]
    prepared.extend(remaining_stored_rows)
    if len(prepared) >= min(limit, 5):
        return prepared[:limit]

    seen_ids = {str(row["canonical_event_id"]) for row in prepared}
    backfill_rows = [
        row
        for row in remaining_rows
        if str(row["canonical_event_id"]) not in seen_ids
        and not _is_ineligible_weekly_candidate(row)
        and not _is_obvious_weekly_noise(row)
    ]
    prepared.extend(_dedupe_semantic_digest_rows(_sort_digest_rows(backfill_rows)))
    prepared = _dedupe_semantic_digest_rows(prepared)
    if len(prepared) >= limit:
        return prepared[:limit]
    if len(prepared) < min(4, limit):
        return prepared[:limit]

    seen_ids = {str(row["canonical_event_id"]) for row in prepared}
    emergency_backfill_rows = [
        row
        for row in remaining_rows
        if str(row["canonical_event_id"]) not in seen_ids
        and not _is_ineligible_weekly_candidate(row)
        and not _is_obvious_weekly_noise(row)
    ]
    prepared.extend(_dedupe_semantic_digest_rows(_sort_digest_rows(emergency_backfill_rows)))
    return _dedupe_semantic_digest_rows(prepared)[:limit]


def _prefer_sent_digest_rows(rows: list[dict[str, object]], *, limit: int) -> list[dict[str, object]]:
    deduped_rows = _dedupe_candidate_rows(rows)
    fixed_rows = [row for row in deduped_rows if _is_fixed_shortlist_row(row)]
    sent_rows = [
        row
        for row in deduped_rows
        if not _is_fixed_shortlist_row(row) and str(row.get("send_status") or "") == "sent"
    ]
    stored_rows = [
        row
        for row in deduped_rows
        if not _is_fixed_shortlist_row(row) and str(row.get("send_status") or "") != "sent"
    ]

    primary_rows = _prepare_digest_rows(fixed_rows + sent_rows, limit=limit)
    if len(primary_rows) >= limit:
        return primary_rows[:limit]

    seen_ids = {str(row["canonical_event_id"]) for row in primary_rows}
    fallback_rows = [
        row
        for row in stored_rows
        if str(row["canonical_event_id"]) not in seen_ids
    ]
    fallback_prepared = _prepare_digest_rows(fallback_rows, limit=limit)
    return _dedupe_candidate_rows(primary_rows + fallback_prepared)[:limit]


def _candidate_identity_keys(candidate: DigestCandidate) -> tuple[str, ...]:
    keys = [f"event:{candidate.canonical_event_id}"]
    if candidate.canonical_url:
        keys.append(f"url:{candidate.canonical_url.strip().lower()}")
    if candidate.title:
        keys.append(f"title:{_normalize_digest_title(candidate.title)}")
    return tuple(keys)


def _dedupe_candidates(candidates: list[DigestCandidate]) -> list[DigestCandidate]:
    deduped: list[DigestCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity_keys = _candidate_identity_keys(candidate)
        if any(key in seen for key in identity_keys):
            continue
        deduped.append(candidate)
        seen.update(identity_keys)
    return deduped


def _dedupe_candidate_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        candidate = DigestCandidate(
            canonical_event_id=str(row["canonical_event_id"]),
            normalized_item_id=str(row["normalized_item_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"]),
            canonical_url=str(row["canonical_url"]),
            published_ts=None,
            score=int(row["score"]),
            summary_text=row.get("summary_text") if isinstance(row, dict) else None,
            event_flags={},
        )
        identity_keys = _candidate_identity_keys(candidate)
        if any(key in seen for key in identity_keys):
            continue
        deduped.append(row)
        seen.update(identity_keys)
    return deduped


def _select_distinct_candidates(
    all_candidates: list[DigestCandidate],
    selected_candidates: list[DigestCandidate],
    limit: int,
) -> list[DigestCandidate]:
    distinct_selected = _dedupe_candidates(selected_candidates)
    if len(distinct_selected) >= limit:
        return distinct_selected[:limit]

    seen: set[str] = set()
    for candidate in distinct_selected:
        seen.update(_candidate_identity_keys(candidate))

    for candidate in all_candidates:
        if any(key in seen for key in _candidate_identity_keys(candidate)):
            continue
        distinct_selected.append(candidate)
        seen.update(_candidate_identity_keys(candidate))
        if len(distinct_selected) >= limit:
            break
    return distinct_selected


def _is_fixed_shortlist_row(row: dict[str, object]) -> bool:
    return bool(row.get("manual_shortlist_signal")) or bool(row.get("manual_digest_force_include"))


class DigestService:
    def __init__(
        self,
        repo_root: Path,
        repository: RadarRepository | None = None,
        claude_client: ClaudeDigestClient | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.settings = load_settings(repo_root)
        configure_logging(self.settings.app.log_level)
        self.repository = repository or RadarRepository(self.settings.app.database_path)
        self.claude_client = claude_client or ClaudeDigestClient(
            enabled=self.settings.digest.claude_digest_enabled,
            api_key=self.settings.integrations.anthropic_api_key,
            model=self.settings.integrations.claude_digest_model,
            timeout_seconds=self.settings.integrations.claude_digest_timeout_seconds,
            max_tokens=self.settings.integrations.claude_digest_max_tokens,
        )
        initialize_database(self.settings.app.database_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")

    def _weekly_group_chat_ids(self) -> tuple[str, ...]:
        group_chat_ids = tuple(
            chat_id for chat_id in self.settings.integrations.telegram_alert_chat_ids if str(chat_id).startswith("-")
        )
        return group_chat_ids

    def _load_shortlist_rows(self, window) -> list[dict[str, object]]:
        group_chat_ids = self._weekly_group_chat_ids()
        group_mode_enabled = self.settings.telegram_group_curation.enabled
        if not group_mode_enabled:
            rows = self.repository.load_digest_candidates_for_week(
                start_date=window.previous_thursday.isoformat(),
                end_date=window.current_thursday.isoformat(),
                limit=self.settings.digest.shortlist_size_before_claude,
                require_canonical_events=self.settings.digest.require_canonical_events,
            )
            manual_rows = self.repository.load_active_shortlist_candidates_for_week(
                start_date=window.previous_thursday.isoformat(),
                end_date=window.current_thursday.isoformat(),
                limit=self.settings.digest.shortlist_size_before_claude,
                require_canonical_events=self.settings.digest.require_canonical_events,
            )
            for row in manual_rows:
                row["manual_shortlist_signal"] = True
            manual_rows.extend(self._load_configured_override_rows(window.week_key))
            for row in rows:
                row.setdefault("manual_shortlist_signal", False)
            return _prepare_digest_rows(
                _dedupe_candidate_rows(manual_rows + rows),
                limit=self.settings.digest.shortlist_size_before_claude,
            )

        sent_rows = self.repository.load_telegram_group_sent_digest_candidates_for_week(
            start_date=window.previous_thursday.isoformat(),
            end_date=window.current_thursday.isoformat(),
            limit=self.settings.digest.shortlist_size_before_claude,
            require_canonical_events=self.settings.digest.require_canonical_events,
            chat_ids=group_chat_ids,
        )
        manual_rows = []
        for row in manual_rows:
            row["manual_shortlist_signal"] = True
        manual_rows.extend(self._load_configured_override_rows(window.week_key))
        if self.settings.telegram_group_curation.enabled and self.settings.telegram_group_curation.reaction_shortlist_enabled:
            reaction_window_start = window.current_thursday - timedelta(
                days=self.settings.telegram_group_curation.shortlist_window_days
            )
            telegram_reaction_rows = self.repository.load_telegram_reaction_digest_candidates_for_week(
                start_date=reaction_window_start.isoformat(),
                end_date=window.current_thursday.isoformat(),
                allowed_reaction_keys=self.settings.telegram_group_curation.shortlist_reaction_allowlist,
                min_unique_reactors=self.settings.telegram_group_curation.shortlist_min_unique_reactors,
                limit=self.settings.digest.shortlist_size_before_claude,
                require_canonical_events=self.settings.digest.require_canonical_events,
            )
            for row in telegram_reaction_rows:
                row["manual_shortlist_signal"] = True
                row["telegram_reaction_shortlist_signal"] = True
            manual_rows.extend(telegram_reaction_rows)
        for row in sent_rows:
            row.setdefault("manual_shortlist_signal", False)
        rows = manual_rows + sent_rows
        return _prefer_sent_digest_rows(rows, limit=self.settings.digest.shortlist_size_before_claude)

    def _load_configured_override_rows(self, week_key: str) -> list[dict[str, object]]:
        path = self.repo_root / "config" / "digest_overrides.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        week_rows = payload.get(week_key, []) if isinstance(payload, dict) else []
        if not isinstance(week_rows, list):
            return []
        rows: list[dict[str, object]] = []
        for entry in week_rows:
            if not isinstance(entry, dict):
                continue
            override_id = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            canonical_url = str(entry.get("canonical_url") or "").strip()
            if not override_id or not title or not canonical_url:
                continue
            signals_json = json.dumps(
                {"event_flags": entry.get("event_flags", {}) if isinstance(entry.get("event_flags"), dict) else {}},
                sort_keys=True,
            )
            source_id = str(entry.get("source_id") or "editorial_override")
            source_name = str(entry.get("source_name") or "Editorial Override")
            published_ts = str(entry.get("published_ts") or "") or None
            score = int(entry.get("score") or 100)
            summary_text = str(entry.get("summary_text") or "").strip() or None
            self.repository.upsert_manual_digest_override_candidate(
                item_id=override_id,
                source_id=source_id,
                source_name=source_name,
                canonical_url=canonical_url,
                title=title,
                summary_text=summary_text,
                published_ts=published_ts,
                score=score,
                signals_json=signals_json,
            )
            rows.append(
                {
                    "canonical_event_id": override_id,
                    "normalized_item_id": override_id,
                    "source_id": source_id,
                    "title": title,
                    "canonical_url": canonical_url,
                    "published_ts": published_ts or "",
                    "score": score,
                    "send_status": "manual_override",
                    "summary_text": summary_text,
                    "signals_json": signals_json,
                    "manual_shortlist_signal": True,
                    "manual_digest_force_include": True,
                }
            )
        return rows

    def build_shortlist(self, week_key: str) -> WeeklyDigestShortlistResult:
        window = resolve_digest_window(week_key)
        pipeline_run_id = self.repository.create_pipeline_run(PipelineName.DIGEST, _settings_snapshot(self.settings))
        digest_run_id = self.repository.create_weekly_digest_run(pipeline_run_id, window.week_key)
        rows = self._load_shortlist_rows(window)
        candidates = hydrate_digest_candidates(rows)
        shortlist_payload = json.dumps(
            [
                {
                    "canonical_event_id": candidate.canonical_event_id,
                    "normalized_item_id": candidate.normalized_item_id,
                    "source_id": candidate.source_id,
                    "title": candidate.title,
                    "canonical_url": candidate.canonical_url,
                    "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
                    "score": candidate.score,
                }
                for candidate in candidates
            ],
            sort_keys=True,
        )
        self.repository.replace_weekly_digest_candidates(digest_run_id, rows)
        self.repository.finish_weekly_digest_run(
            digest_run_id,
            PipelineStatus.COMPLETED,
            shortlist_payload,
            None,
        )
        return WeeklyDigestShortlistResult(
            pipeline_run_id=pipeline_run_id,
            digest_run_id=digest_run_id,
            week_key=window.week_key,
            candidate_count=len(candidates),
            candidates=candidates,
        )

    def build_digest(self, week_key: str, output_path: Path | None = None) -> WeeklyDigestBuildResult:
        window = resolve_digest_window(week_key)
        normalized_week_key = window.week_key
        output_path = output_path or build_default_output_path(self.repo_root, normalized_week_key)
        report_output_path = output_path.with_name(f"{output_path.stem}.report.md")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_output_path.parent.mkdir(parents=True, exist_ok=True)

        pipeline_run_id = self.repository.create_pipeline_run(PipelineName.DIGEST, _settings_snapshot(self.settings))
        digest_run_id = self.repository.create_weekly_digest_run(pipeline_run_id, normalized_week_key)
        fallback_reason: str | None = None
        selection_fallback_reason: str | None = None
        final_markdown = ""
        claude_used = False

        try:
            rows = self._load_shortlist_rows(window)
            mandatory_event_ids = tuple(
                str(row["canonical_event_id"])
                for row in rows
                if bool(row.get("manual_shortlist_signal")) or bool(row.get("manual_digest_force_include"))
            )
            candidates = hydrate_digest_candidates(rows)
            if self.settings.telegram_group_curation.enabled and len(candidates) < self.settings.digest.stories_per_digest:
                raise ValueError(
                    f"Only {len(candidates)} eligible group stories available for weekly digest in {normalized_week_key}."
                )
            shortlist_payload = json.dumps(
                [
                    {
                        "canonical_event_id": candidate.canonical_event_id,
                        "normalized_item_id": candidate.normalized_item_id,
                        "source_id": candidate.source_id,
                        "title": candidate.title,
                        "canonical_url": candidate.canonical_url,
                        "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
                        "score": candidate.score,
                    }
                    for candidate in candidates
                ],
                sort_keys=True,
            )
            self.repository.replace_weekly_digest_candidates(digest_run_id, rows)

            selected_candidates = _select_distinct_candidates(candidates, candidates[:5], limit=5)
            mandatory_candidates = [
                candidate for candidate in candidates if candidate.canonical_event_id in set(mandatory_event_ids)
            ]
            if candidates and self.claude_client.is_available:
                selection_prompt = build_claude_selection_prompt(
                    window,
                    candidates,
                    self.settings.digest.claude_digest_max_input_items,
                    mandatory_ids=mandatory_event_ids,
                )
                try:
                    selected_ids = self.claude_client.select_top_story_ids(
                        selection_prompt,
                        allowed_ids={candidate.canonical_event_id for candidate in candidates},
                        exact_count=min(5, len(candidates)),
                    )
                    selected_candidates = [
                        candidate for candidate in candidates if candidate.canonical_event_id in set(selected_ids)
                    ]
                    selected_candidates.sort(key=lambda candidate: selected_ids.index(candidate.canonical_event_id))
                    selected_candidates = _select_distinct_candidates(
                        candidates,
                        mandatory_candidates + selected_candidates,
                        limit=5,
                    )
                except ClaudeDigestUnavailableError as exc:
                    selection_fallback_reason = str(exc)
                    LOGGER.warning(
                        "Claude digest selection unavailable for week=%s reason=%s",
                        normalized_week_key,
                        exc,
                    )
            elif self.settings.digest.claude_digest_enabled:
                selection_fallback_reason = "Claude digest synthesis is enabled but not fully configured."
                LOGGER.warning(
                    "Claude digest selection skipped for week=%s reason=%s",
                    normalized_week_key,
                    selection_fallback_reason,
                )

            selected_candidates = _select_distinct_candidates(
                candidates,
                mandatory_candidates + selected_candidates,
                limit=5,
            )

            final_markdown = build_digest_html(window.title, selected_candidates)
            if selected_candidates and self.claude_client.is_available:
                writer_prompt = build_claude_writer_prompt(window, selected_candidates)
                try:
                    final_markdown = self.claude_client.generate_telegram_digest(
                        writer_prompt,
                        expected_title=window.title,
                    )
                    claude_used = True
                except ClaudeDigestUnavailableError as exc:
                    fallback_reason = str(exc)
                    final_markdown = build_digest_html(window.title, selected_candidates)
                    LOGGER.warning("Claude digest writing unavailable for week=%s reason=%s", normalized_week_key, exc)
            if fallback_reason is None and not claude_used and selection_fallback_reason:
                fallback_reason = selection_fallback_reason

            output_path.write_text(final_markdown, encoding="utf-8")
            report_output_path.write_text(
                build_digest_markdown(
                    normalized_week_key,
                    selected_candidates,
                    claude_used=claude_used,
                    fallback_reason=fallback_reason,
                ),
                encoding="utf-8",
            )
            self.repository.finish_weekly_digest_run(
                digest_run_id=digest_run_id,
                status=PipelineStatus.COMPLETED,
                shortlist_json=shortlist_payload,
                final_digest_markdown=final_markdown,
            )
            self.repository.finish_pipeline_run(
                pipeline_run_id,
                PipelineStatus.COMPLETED,
                {
                    "week_key": normalized_week_key,
                    "candidate_count": len(candidates),
                    "claude_used": claude_used,
                    "fallback_reason": fallback_reason,
                    "output_path": str(output_path),
                    "report_output_path": str(report_output_path),
                    "digest_title": window.title,
                },
            )
            return WeeklyDigestBuildResult(
                pipeline_run_id=pipeline_run_id,
                digest_run_id=digest_run_id,
                week_key=normalized_week_key,
                output_path=output_path,
                candidate_count=len(candidates),
                claude_used=claude_used,
                fallback_reason=fallback_reason,
            )
        except Exception:
            self.repository.finish_weekly_digest_run(
                digest_run_id=digest_run_id,
                status=PipelineStatus.FAILED,
                shortlist_json=None,
                final_digest_markdown=final_markdown,
            )
            self.repository.finish_pipeline_run(
                pipeline_run_id,
                PipelineStatus.FAILED,
                {"week_key": normalized_week_key, "error": "Weekly digest build failed before completion."},
            )
            raise
