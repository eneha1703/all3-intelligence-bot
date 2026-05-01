"""End-to-end weekly digest build service."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
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


@dataclass(frozen=True)
class WeeklyDigestBuildResult:
    pipeline_run_id: str
    digest_run_id: str
    week_key: str
    output_path: Path
    candidate_count: int
    claude_used: bool
    fallback_reason: str | None


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


def _sort_digest_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
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
    non_noise_rows = [row for row in rows if not _is_obvious_weekly_noise(row)]
    prepared = _dedupe_semantic_digest_rows(_sort_digest_rows(non_noise_rows))
    if len(prepared) >= min(limit, 5):
        return prepared[:limit]

    seen_ids = {str(row["canonical_event_id"]) for row in prepared}
    backfill_rows = [row for row in rows if str(row["canonical_event_id"]) not in seen_ids]
    prepared.extend(_dedupe_semantic_digest_rows(_sort_digest_rows(backfill_rows)))
    return _dedupe_semantic_digest_rows(prepared)[:limit]


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
        final_markdown = ""
        claude_used = False

        try:
            rows = self.repository.load_digest_candidates_for_week(
                start_date=window.previous_thursday.isoformat(),
                end_date=window.current_thursday.isoformat(),
                limit=self.settings.digest.shortlist_size_before_claude,
                require_canonical_events=self.settings.digest.require_canonical_events,
            )
            rows = _dedupe_candidate_rows(rows)
            rows = _prepare_digest_rows(rows, limit=self.settings.digest.shortlist_size_before_claude)
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

            selected_candidates = _select_distinct_candidates(candidates, candidates[:5], limit=5)
            if candidates and self.claude_client.is_available:
                selection_prompt = build_claude_selection_prompt(
                    window,
                    candidates,
                    self.settings.digest.claude_digest_max_input_items,
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
                    selected_candidates = _select_distinct_candidates(candidates, selected_candidates, limit=5)
                except ClaudeDigestUnavailableError as exc:
                    fallback_reason = str(exc)
                    LOGGER.warning("Claude digest selection unavailable for week=%s reason=%s", normalized_week_key, exc)
            elif self.settings.digest.claude_digest_enabled:
                fallback_reason = "Claude digest synthesis is enabled but not fully configured."
                LOGGER.warning("Claude digest selection skipped for week=%s reason=%s", normalized_week_key, fallback_reason)

            final_markdown = build_digest_html(window.title, selected_candidates)
            if selected_candidates and self.claude_client.is_available and fallback_reason is None:
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

            output_path.write_text(final_markdown, encoding="utf-8")
            report_output_path.write_text(build_digest_markdown(normalized_week_key, selected_candidates), encoding="utf-8")
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
