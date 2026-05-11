"""Prompt-context helpers for selective editorial memory injection."""

from __future__ import annotations

from pathlib import Path

from all3_radar.editorial_memory.service import load_digest_example_seed, load_rules


def build_digest_memory_context(
    repo_root: Path,
    *,
    max_rules: int = 6,
    max_good_examples: int = 3,
    max_bad_examples: int = 3,
) -> str:
    rules_payload = load_rules(repo_root / "config" / "editorial_memory_rules.yaml")
    scoped_rules = [
        rule
        for rule in rules_payload["rules"]
        if "digest_writing" in tuple(rule.get("scope", ())) and str(rule.get("status", "")).strip().lower() == "active"
    ][:max_rules]

    examples = load_digest_example_seed(repo_root)
    good_examples = [example for example in examples if example.kind == "digest_good"][:max_good_examples]
    bad_examples = [example for example in examples if example.kind == "digest_bad"][:max_bad_examples]

    lines = ["Editorial memory rules:"]
    for rule in scoped_rules:
        lines.append(f"- {rule['id']}: {rule['summary']}")

    lines.append("")
    lines.append("Editorial memory good examples:")
    for example in good_examples:
        lines.append(f"- Headline: {example.title}")
        lines.append(f"  Notes: {', '.join(example.metadata.get('notes', []))}")
        lines.append(f"  Body: {example.feedback_text}")

    lines.append("")
    lines.append("Editorial memory bad examples:")
    for example in bad_examples:
        lines.append(f"- Headline: {example.title}")
        lines.append(f"  Notes: {', '.join(example.metadata.get('notes', []))}")
        lines.append(f"  Body: {example.feedback_text}")

    return "\n".join(lines).strip()
