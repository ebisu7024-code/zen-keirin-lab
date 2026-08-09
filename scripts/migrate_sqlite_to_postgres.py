from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLiteの既存DBをPostgreSQL/Supabaseへ取り込む")
    parser.add_argument(
        "--sqlite-db",
        default="data/zen_keirin_lab.sqlite3",
        help="取込元SQLite DBのパス",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="PostgreSQL接続URL。未指定なら ZEN_KEIRIN_DATABASE_URL / DATABASE_URL を使う",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parents[1]
    sqlite_path = Path(args.sqlite_db)
    if not sqlite_path.is_absolute():
        sqlite_path = project_dir / sqlite_path

    if args.database_url:
        os.environ["ZEN_KEIRIN_DATABASE_URL"] = args.database_url

    sys.path.insert(0, str(project_dir))
    import app

    if app.database_backend() != "postgres":
        print("ZEN_KEIRIN_DATABASE_URL または DATABASE_URL にPostgreSQL接続URLを設定してください。", file=sys.stderr)
        return 2

    app.validate_database_file(sqlite_path)
    app.init_db()
    counts = app.import_sqlite_database_to_active_db(sqlite_path)
    print(
        "取込完了: "
        f"レース{counts.get('races', 0):,}件 / "
        f"選手{counts.get('riders', 0):,}件 / "
        f"買い目{counts.get('bets', 0):,}件 / "
        f"結果{counts.get('results', 0):,}件"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
