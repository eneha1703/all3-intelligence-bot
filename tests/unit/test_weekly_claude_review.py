from pathlib import Path

from all3_radar.app.editorial_memory_cli import build_parser
from all3_radar.digest.claude_client import ClaudeDigestClient, ClaudeDigestUnavailableError
from all3_radar.editorial_memory.models import EditorialMemoryExample
from all3_radar.editorial_memory.weekly_review import (
    _dedupe_story_rows,
    _load_review_memory_examples,
    build_weekly_review_prompt,
)
from all3_radar.editorial_memory.paths import (
    resolve_editorial_memory_database_path,
    resolve_editorial_memory_schema_path,
)
from all3_radar.editorial_memory.repository import EditorialMemoryRepository


def test_weekly_review_prompt_has_required_sections() -> None:
    prompt = build_weekly_review_prompt(
        week_key="2026-W20",
        story_rows=[
            {
                "title": "Story A",
                "source_id": "source_a",
                "score": 80,
                "send_status": "sent",
                "skip_reason": None,
            }
        ],
        shortlist_rows=[],
        reaction_rows=[],
        memory_examples=[
            EditorialMemoryExample(
                kind="summary_bad",
                title="Broken tail example",
                feedback_text="Sentence ended on a dangling fragment.",
                decision_tags=("broken_tail",),
                linked_rule_ids=("summary_no_broken_tails",),
            )
        ],
    )

    assert prompt.startswith("# Weekly Claude Radar Review | 2026-W20")
    assert "## Top Misses" in prompt
    assert "## Weak Sends" in prompt
    assert "## Writing Failures" in prompt
    assert "## Suggested Rule Updates" in prompt
    assert '"title": "Story A"' in prompt
    assert "Broken tail example" in prompt


def test_claude_digest_client_requires_review_title(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    monkeypatch.setattr(ClaudeDigestClient, "_request_text", lambda self, prompt: "Wrong title\n\nBody")

    try:
        client.generate_weekly_review("prompt", expected_title="# Weekly Claude Radar Review | 2026-W20")
    except ClaudeDigestUnavailableError as exc:
        assert "required title line" in str(exc)
    else:
        raise AssertionError("Expected ClaudeDigestUnavailableError for missing weekly review title")


def test_claude_digest_client_accepts_wrapped_review_title(monkeypatch) -> None:
    client = ClaudeDigestClient(
        enabled=True,
        api_key="secret",
        model="claude-test",
        timeout_seconds=10,
        max_tokens=500,
    )

    monkeypatch.setattr(
        ClaudeDigestClient,
        "_request_text",
        lambda self, prompt: "Here is the review you asked for.\n\n# Weekly Claude Radar Review | 2026-W20\n\n## Top Misses\n- Example",
    )

    result = client.generate_weekly_review("prompt", expected_title="# Weekly Claude Radar Review | 2026-W20")

    assert result.startswith("# Weekly Claude Radar Review | 2026-W20")


def test_editorial_memory_cli_accepts_review_build_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["review", "build", "--week", "2026-W20", "--output", "data/review.md"])

    assert args.group == "review"
    assert args.command == "build"
    assert args.week == "2026-W20"
    assert args.output == "data/review.md"


def test_dedupe_story_rows_collapses_duplicate_candidates() -> None:
    rows = [
        {"canonical_event_id": "evt-1", "canonical_url": "https://example.com/1", "title": "Story A"},
        {"canonical_event_id": "evt-1", "canonical_url": "https://example.com/1", "title": "Story A"},
        {"canonical_event_id": "", "canonical_url": "https://example.com/2", "title": "Story B"},
        {"canonical_event_id": None, "canonical_url": "https://example.com/2", "title": "Story B"},
        {"canonical_event_id": None, "canonical_url": "", "title": "Story C"},
    ]

    deduped = _dedupe_story_rows(rows)

    assert [row["title"] for row in deduped] == ["Story A", "Story B", "Story C"]


def test_load_review_memory_examples_falls_back_to_seed_examples(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repository = EditorialMemoryRepository(
        resolve_editorial_memory_database_path(tmp_path),
        resolve_editorial_memory_schema_path(repo_root),
    )
    repository.initialize()

    examples = _load_review_memory_examples(repository, repo_root)

    assert examples
    assert any(example.kind == "summary_bad" for example in examples)
