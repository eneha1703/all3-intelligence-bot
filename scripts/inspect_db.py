import sqlite3
from pathlib import Path


def main() -> int:
    db_path = Path("data/all3_radar.db")
    if not db_path.exists():
        print("Database does not exist yet.")
        return 1

    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for row in cursor.fetchall():
            print(row[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
