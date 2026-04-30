"""End-to-end weekly digest build service."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from all3_radar.config.loader import load_settings
from all3_radar.digest.claude_client import ClaudeDigestClient, ClaudeDigestUnavailableError
from all3_radar.digest.corpus import (
    build_claude_selection_prompt,
    build_claude_writer_prompt,
    build_default_output_path,
    hydrate_digest_candidates,
    resolve_digest_window,
)
from all3_radar.digest.writer import build_digest_html, build_digest_markdown
from all3_radar.domain.enums import PipelineName, PipelineStatus
from all3_radar.observability.logging import configure_logging
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository

LOGGER = logging.getLogger(__name__)


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

            selected_candidates = candidates[:5]
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
