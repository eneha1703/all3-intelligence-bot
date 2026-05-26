"""Send the latest weekly digest markdown to Telegram Bot 2."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path


def _latest_digest_path(repo_root: Path) -> Path:
    candidates = sorted(
        repo_root.glob("data/weekly_digest_*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    digest_files = [path for path in candidates if not path.name.endswith(".report.md")]
    if not digest_files:
        raise SystemExit("No weekly digest artifact found.")
    return digest_files[0]


def _validate_digest(message: str) -> None:
    if not message.startswith("Top 5 News Highlights |"):
        raise SystemExit("Digest does not start with the required title prefix.")
    if len(message) >= 4096:
        raise SystemExit(f"Digest message is too long for a single Telegram message: {len(message)}")
    numbered_items = re.findall(r"(?m)^\s*\d+\.\s*<b>", message)
    if len(numbered_items) < 5:
        raise SystemExit(f"Digest must contain at least 5 numbered items, found {len(numbered_items)}.")
    if '<a href="' not in message or ">Link</a>" not in message:
        raise SystemExit("Digest is missing embedded HTML Link anchors.")
    if "example.com" in message:
        raise SystemExit("Digest still contains example.com placeholder links.")

    visible_text = re.sub(r'<a href="[^"]+">Link</a>', "Link", message)
    if re.search(r"https?://", visible_text):
        raise SystemExit("Digest contains raw visible URLs outside href attributes.")


def main() -> int:
    repo_root = Path.cwd()
    digest_path = _latest_digest_path(repo_root)
    message = digest_path.read_text(encoding="utf-8").strip()
    _validate_digest(message)

    first_line = message.splitlines()[0] if message.splitlines() else ""
    print(f"Digest artifact: {digest_path}")
    print(f"Digest first line: {first_line}")
    print(f"Digest message length: {len(message)}")

    bot_token = (os.environ.get("TELEGRAM_DIGEST_BOT_TOKEN") or "").strip()
    chat_ids_raw = (os.environ.get("TELEGRAM_DIGEST_CHAT_IDS") or "").strip()
    if not bot_token:
        raise SystemExit("TELEGRAM_DIGEST_BOT_TOKEN is empty.")
    if not chat_ids_raw:
        raise SystemExit("TELEGRAM_DIGEST_CHAT_IDS is empty.")

    chat_ids = [part.strip() for part in chat_ids_raw.split(",") if part.strip()]
    if not chat_ids:
        raise SystemExit("No valid TELEGRAM_DIGEST_CHAT_IDS were provided.")

    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for chat_id in chat_ids:
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise SystemExit(f"Telegram send failed for chat_id={chat_id}: {body}")
        masked_chat = f"{chat_id[:4]}***{chat_id[-4:]}" if len(chat_id) >= 8 else "***"
        print(f"Sent digest to Bot 2 chat_id={masked_chat} ok=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
