"""Render Telegram-style preview cards from a web-discovery JSON artifact."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
RAW_URL_RE = re.compile(r"https?://\S+")


def _load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Web discovery JSON must be an object: {path}")
    return payload


def _find_latest_json(input_dir: Path) -> Path:
    candidates = sorted(input_dir.glob("web-discovery-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    candidates = [path for path in candidates if not path.name.startswith("web-discovery-failed-")]
    if not candidates:
        raise FileNotFoundError(f"No web-discovery-*.json files found in {input_dir}")
    return candidates[0]


def _compact_text(value: str | None) -> str:
    return WHITESPACE_RE.sub(" ", value or "").strip()


def _summary_for_card(summary: str | None, *, max_sentences: int = 2, max_chars: int = 560) -> str:
    cleaned = _compact_text(summary)
    if not cleaned:
        return ""
    cleaned = RAW_URL_RE.sub("", cleaned)
    sentences = [sentence.strip() for sentence in SENTENCE_RE.split(cleaned) if sentence.strip()]
    selected = " ".join(sentences[:max_sentences]) if sentences else cleaned
    if len(selected) <= max_chars:
        return selected
    truncated = selected[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{truncated}."


def _priority(candidate: dict[str, Any]) -> str:
    source_name = str(candidate.get("source_name") or "").lower()
    url = str(candidate.get("url") or "").lower()
    confidence = str(candidate.get("confidence") or "").lower()
    if any(marker in source_name or marker in url for marker in ("pr newswire", "business wire", "globe newswire", "globenewswire", "stocktitan", "stock titan")):
        return "verify_primary_source"
    if confidence == "high":
        return "likely_post"
    return "watch_only"


def _candidate_from_item(item: dict[str, Any]) -> dict[str, Any]:
    candidate = item.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("Accepted candidate item is missing candidate object")
    return candidate


def _render_card(candidate: dict[str, Any], index: int) -> str:
    title = _compact_text(str(candidate.get("title") or ""))
    url = _compact_text(str(candidate.get("url") or ""))
    summary = _summary_for_card(candidate.get("summary") if isinstance(candidate.get("summary"), str) else None)
    source = _compact_text(str(candidate.get("source_name") or "unknown source"))
    confidence = _compact_text(str(candidate.get("confidence") or "unknown"))
    priority = _priority(candidate)
    if not title or not url or not summary:
        raise ValueError(f"Candidate #{index} is missing title, URL, or summary")
    card = "\n\n".join(
        [
            f"<b>{html.escape(title)}</b>",
            html.escape(summary),
            f'<a href="{html.escape(url, quote=True)}">Link</a>',
        ]
    )
    return "\n".join(
        [
            f"## Candidate {index}: {priority}",
            "",
            f"- Source: `{source}`",
            f"- Confidence: `{confidence}`",
            "",
            "```html",
            card,
            "```",
            "",
        ]
    )


def build_preview_markdown(payload: dict[str, Any], *, source_path: Path) -> str:
    accepted = payload.get("accepted_candidates")
    if not isinstance(accepted, list):
        raise ValueError("Web discovery JSON must contain accepted_candidates list")
    cards = [_render_card(_candidate_from_item(item), index) for index, item in enumerate(accepted, start=1)]
    lines = [
        "# Web Discovery Telegram Preview",
        "",
        f"Source JSON: `{source_path}`",
        f"Generated at: `{payload.get('generated_at', 'unknown')}`",
        f"Accepted candidates: `{len(accepted)}`",
        "",
        "These are preview-only Telegram HTML cards. Nothing was sent.",
        "",
    ]
    if cards:
        lines.extend(cards)
    else:
        lines.append("No accepted candidates to preview.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, default=None, help="Specific web-discovery JSON file to preview.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/web-discovery"), help="Directory to scan for latest web-discovery JSON.")
    parser.add_argument("--output", type=Path, default=Path("data/web-discovery/web-discovery-telegram-preview.md"))
    args = parser.parse_args()

    input_json = args.input_json or _find_latest_json(args.input_dir)
    payload = _load_payload(input_json)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_preview_markdown(payload, source_path=input_json), encoding="utf-8")
    print(f"Preview written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
