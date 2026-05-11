from pathlib import Path

from all3_radar.app.editorial_memory_cli import build_parser
from all3_radar.digest.claude_client import ClaudeDigestClient, ClaudeDigestUnavailableError
from all3_radar.editorial_memory.models import EditorialMemoryExample
from all3_radar.editorial_memory.weekly_review import build_weekly_review_prompt


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


def test_editorial_memory_cli_accepts_review_build_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["review", "build", "--week", "2026-W20", "--output", "data/review.md"])

    assert args.group == "review"
    assert args.command == "build"
    assert args.week == "2026-W20"
    assert args.output == "data/review.md"
