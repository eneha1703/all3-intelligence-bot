"""One-off import of a local SQLite DB into Turso/libSQL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from all3_radar.storage.importer import import_sqlite_database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a local SQLite database into a Turso/libSQL database."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to the local SQLite database that should be imported.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows per batch insert. Default: 500",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_database_path = Path(args.source).expanduser().resolve()
    schema_path = REPO_ROOT / "src" / "all3_radar" / "storage" / "schema.sql"

    database_url = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
    auth_token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
    if not database_url or not auth_token:
        raise SystemExit(
            "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set before running this import."
        )

    imported_counts = import_sqlite_database(
        source_database_path=source_database_path,
        target_database_path=Path("remote-import.db"),
        schema_path=schema_path,
        batch_size=args.batch_size,
    )

    total_rows = sum(imported_counts.values())
    print(f"Imported {len(imported_counts)} tables and {total_rows} rows into {database_url}.")
    for table_name, row_count in imported_counts.items():
        print(f" - {table_name}: {row_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
