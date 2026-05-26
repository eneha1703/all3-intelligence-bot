"""Small GitLab CI helpers for the temporary SQLite state bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


TABLES_TO_COUNT = (
    "sources",
    "pipeline_runs",
    "raw_items",
    "normalized_items",
    "radar_decisions",
    "canonical_events",
    "event_members",
    "telegram_deliveries",
    "telegram_group_messages",
    "telegram_group_message_links",
    "telegram_reaction_picks",
    "weekly_digest_runs",
    "weekly_digest_candidates",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    try:
        counts: dict[str, int] = {}
        for table_name in TABLES_TO_COUNT:
            try:
                counts[table_name] = int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
            except sqlite3.Error:
                counts[table_name] = -1
        return counts
    finally:
        connection.close()


def _integrity_check(database_path: Path) -> str:
    connection = sqlite3.connect(database_path)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def restore_state(seed_zip: Path, database_path: Path) -> None:
    if database_path.exists():
        print(f"State DB already present: {database_path} ({database_path.stat().st_size} bytes)")
        print(f"sha256={_sha256(database_path)}")
        return

    if not seed_zip.exists():
        raise SystemExit(f"State DB is missing and seed zip does not exist: {seed_zip}")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(seed_zip) as archive:
        member_name = next(
            (name for name in archive.namelist() if Path(name).name == "all3_radar.db"),
            None,
        )
        if not member_name:
            raise SystemExit(f"Seed zip does not contain all3_radar.db: {seed_zip}")
        with archive.open(member_name) as source, database_path.open("wb") as target:
            target.write(source.read())

    print(f"Restored state DB from seed: {seed_zip}")
    print(f"database={database_path} size={database_path.stat().st_size} sha256={_sha256(database_path)}")


def write_snapshot(database_path: Path, output_dir: Path, label: str) -> None:
    if not database_path.exists():
        raise SystemExit(f"Cannot snapshot missing database: {database_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_path": str(database_path),
        "file_size_bytes": database_path.stat().st_size,
        "sha256": _sha256(database_path),
        "integrity_check": _integrity_check(database_path),
        "table_rows": _table_counts(database_path),
    }
    manifest_path = output_dir / f"{label}-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    zip_path = output_dir / f"{label}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(database_path, "all3_radar.db")
        archive.write(manifest_path, manifest_path.name)

    print(f"Wrote state snapshot: {zip_path}")
    print(f"manifest={manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="GitLab CI state helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore_parser = subparsers.add_parser("restore", help="Restore DB from seed when cache is empty")
    restore_parser.add_argument("--seed-zip", required=True, type=Path)
    restore_parser.add_argument("--database", required=True, type=Path)

    snapshot_parser = subparsers.add_parser("snapshot", help="Write a compressed DB snapshot artifact")
    snapshot_parser.add_argument("--database", required=True, type=Path)
    snapshot_parser.add_argument("--output-dir", required=True, type=Path)
    snapshot_parser.add_argument("--label", required=True)

    args = parser.parse_args()
    if args.command == "restore":
        restore_state(args.seed_zip, args.database)
    elif args.command == "snapshot":
        write_snapshot(args.database, args.output_dir, args.label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
