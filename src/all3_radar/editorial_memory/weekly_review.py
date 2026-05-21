"""Weekly Claude review helpers for radar learning loops."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from all3_radar.config.loader import load_settings
from all3_radar.digest.claude_client import ClaudeDigestClient, ClaudeDigestUnavailableError
from all3_radar.digest.corpus import resolve_digest_window
from all3_radar.editorial_memory.paths import (
    resolve_editorial_memory_database_path,
    resolve_editorial_memory_schema_path,
)
from all3_radar.editorial_memory.repository import EditorialMemoryRepository
from all3_radar.editorial_memory.service import load_digest_example_seed, load_manual_seed_examples
from all3_radar.storage.db import initialize_database
from all3_radar.storage.repositories import RadarRepository


@dataclass(frozen=True)
class WeeklyClaudeReviewResult:
    week_key: str
    output_path: Path
    claude_used: bool
    fallback_reason: str | None


def build_weekly_review_prompt(
    *,
    week_key: str,
    story_rows: list[dict],
    shortlist_rows: list[dict],
    reaction_rows: list[dict],
    memory_examples: list[object],
) -> str:
    payload = {
        "week_key": week_key,
        "stories": story_rows,
        "active_shortlist": shortlist_rows,
        "reaction_shortlist": reaction_rows,
        "editorial_memory_examples": [
            {
                "kind": example.kind,
                "title": example.title,
                "feedback_text": example.feedback_text,
                "decision_tags": list(example.decision_tags),
                "linked_rule_ids": list(example.linked_rule_ids),
                "source": example.source,
                "week_key": example.week_key,
            }
            for example in memory_examples
        ],
    }
    return "\n".join(
        [
            f"# Weekly Claude Radar Review | {week_key}",
            "",
            "Review the weekly radar output and produce a short internal learning memo.",
            "Focus on four things only:",
            "1. Top missed opportunities: up to 5 stories that look stronger than what was sent.",
            "2. Weak sends: up to 3 sent stories that were weaker than better non-sent options.",
            "3. Writing failures: recurring Bot 1 or digest writing problems visible in the examples or summaries.",
            "4. Rule update candidates: up to 3 concrete rule or prompt changes worth testing next.",
            "",
            "Be specific, evidence-backed, and compact.",
            "Do not rewrite the stories themselves.",
            "Do not invent facts.",
            "Return markdown only.",
            "Start exactly with '# Weekly Claude Radar Review | "
            + week_key
            + "'.",
            "Use these markdown sections exactly:",
            "## Top Misses",
            "## Weak Sends",
            "## Writing Failures",
            "## Suggested Rule Updates",
            "",
            "Weekly review JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )


class WeeklyClaudeReviewService:
    def __init__(
        self,
        repo_root: Path,
        repository: RadarRepository | None = None,
        editorial_memory_repository: EditorialMemoryRepository | None = None,
        claude_client: ClaudeDigestClient | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.settings = load_settings(repo_root)
        self.repository = repository or RadarRepository(self.settings.app.database_path)
        self.editorial_memory_repository = editorial_memory_repository or EditorialMemoryRepository(
            resolve_editorial_memory_database_path(repo_root),
            resolve_editorial_memory_schema_path(repo_root),
        )
        self.claude_client = claude_client or ClaudeDigestClient(
            enabled=self.settings.digest.claude_digest_enabled,
            api_key=self.settings.integrations.anthropic_api_key,
            model=self.settings.integrations.claude_digest_model,
            timeout_seconds=self.settings.integrations.claude_digest_timeout_seconds,
            max_tokens=self.settings.integrations.claude_digest_max_tokens,
        )
        initialize_database(self.settings.app.database_path, repo_root / "src" / "all3_radar" / "storage" / "schema.sql")
        self.editorial_memory_repository.initialize()

    def build(self, *, week_key: str, output_path: Path | None = None) -> WeeklyClaudeReviewResult:
        window = resolve_digest_window(week_key)
        output_path = output_path or self.repo_root / "data" / f"weekly_claude_review_{window.week_key}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        story_rows = _dedupe_story_rows(
            self.repository.load_weekly_review_story_rows(
            start_date=window.start_date.isoformat(),
            end_date=window.current_thursday.isoformat(),
            limit=30,
            )
        )
        shortlist_rows = self.repository.load_active_shortlist_candidates_for_week(
            start_date=window.start_date.isoformat(),
            end_date=window.current_thursday.isoformat(),
            limit=10,
            require_canonical_events=self.settings.digest.require_canonical_events,
        )
        reaction_rows: list[dict] = []
        if self.settings.telegram_group_curation.enabled and self.settings.telegram_group_curation.reaction_shortlist_enabled:
            reaction_rows = self.repository.load_telegram_reaction_digest_candidates_for_week(
                start_date=window.start_date.isoformat(),
                end_date=window.current_thursday.isoformat(),
                allowed_reaction_keys=self.settings.telegram_group_curation.shortlist_reaction_allowlist,
                min_unique_reactors=self.settings.telegram_group_curation.shortlist_min_unique_reactors,
                limit=10,
                require_canonical_events=self.settings.digest.require_canonical_events,
            )
        memory_examples = _load_review_memory_examples(self.editorial_memory_repository, self.repo_root)

        prompt = build_weekly_review_prompt(
            week_key=window.week_key,
            story_rows=story_rows,
            shortlist_rows=shortlist_rows,
            reaction_rows=reaction_rows,
            memory_examples=memory_examples,
        )

        fallback_reason: str | None = None
        claude_used = False
        review_markdown = _deterministic_fallback_review(window.week_key, story_rows, memory_examples)
        if self.claude_client.is_available:
            try:
                review_markdown = self.claude_client.generate_weekly_review(prompt, expected_title=f"# Weekly Claude Radar Review | {window.week_key}")
                claude_used = True
            except ClaudeDigestUnavailableError as exc:
                fallback_reason = str(exc)

        if not claude_used and fallback_reason:
            review_markdown = _inject_fallback_reason(review_markdown, fallback_reason)

        output_path.write_text(review_markdown, encoding="utf-8")
        return WeeklyClaudeReviewResult(
            week_key=window.week_key,
            output_path=output_path,
            claude_used=claude_used,
            fallback_reason=fallback_reason,
        )


def _deterministic_fallback_review(week_key: str, story_rows: list[dict], memory_examples: list[object]) -> str:
    sent_rows = [row for row in story_rows if str(row.get("send_status")) == "sent"][:3]
    non_sent_rows = [row for row in story_rows if str(row.get("send_status")) != "sent"][:5]
    summary_bad_examples = [example for example in memory_examples if example.kind == "summary_bad"][:3]
    lines = [
        f"# Weekly Claude Radar Review | {week_key}",
        "",
        "## Top Misses",
    ]
    if non_sent_rows:
        for row in non_sent_rows:
            lines.append(f"- {row['title']} ({row['source_id']}, score {row['score']}, status {row['send_status']})")
    else:
        lines.append("- No obvious non-sent review candidates were available in the fallback view.")
    lines.extend(["", "## Weak Sends"])
    if sent_rows:
        for row in sent_rows:
            lines.append(f"- {row['title']} ({row['source_id']}, score {row['score']})")
    else:
        lines.append("- No sent stories were available in the fallback view.")
    lines.extend(["", "## Writing Failures"])
    if summary_bad_examples:
        for example in summary_bad_examples:
            lines.append(f"- {example.title}: {example.feedback_text}")
    else:
        lines.append("- No stored bad-summary examples were available.")
    lines.extend(
        [
            "",
            "## Suggested Rule Updates",
            "- Claude review fallback was used; inspect the candidate set and stored writing examples before making rule changes.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _dedupe_story_rows(story_rows: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for row in story_rows:
        canonical_event_id = str(row.get("canonical_event_id") or "").strip()
        canonical_url = str(row.get("canonical_url") or "").strip()
        title = str(row.get("title") or "").strip()
        fingerprint = canonical_event_id or canonical_url or title
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(row)
    return deduped


def _load_review_memory_examples(
    repository: EditorialMemoryRepository,
    repo_root: Path,
) -> list[object]:
    stored_examples = repository.list_examples(limit=12)
    if stored_examples:
        return stored_examples
    fallback_examples = load_manual_seed_examples(repo_root) + load_digest_example_seed(repo_root)
    return fallback_examples[:12]


def _inject_fallback_reason(review_markdown: str, fallback_reason: str) -> str:
    note = f"_Fallback reason: {fallback_reason}_"
    lines = review_markdown.splitlines()
    if len(lines) >= 2 and lines[0].startswith("# Weekly Claude Radar Review |"):
        return "\n".join([lines[0], "", note, *lines[1:]]).strip() + "\n"
    return f"{review_markdown.rstrip()}\n\n{note}\n"
