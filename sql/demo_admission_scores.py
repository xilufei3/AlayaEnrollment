from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CREATE_SQL_PATH = SCRIPT_DIR / "manual" / "admission_scores" / "create.sql"
IMPORT_SQL_PATH = SCRIPT_DIR / "manual" / "admission_scores" / "import.sql"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "db" / "admission_scores_demo.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, load, and query the admission_scores demo database."
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path, or :memory: for an in-memory run.",
    )
    parser.add_argument(
        "--province",
        default="安徽",
        help="Province used for the point lookup and history query.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2024,
        help="Year used for the point lookup and sample year query.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the target database file before loading data.",
    )
    return parser


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def resolve_db_path(raw_path: str) -> str:
    if raw_path == ":memory:":
        return raw_path
    return str(Path(raw_path).resolve())


def reset_database_file(db_path: str) -> None:
    if db_path == ":memory:":
        return

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()


def execute_scripts(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        execute_scripts_on_connection(conn)


def execute_scripts_on_connection(conn: sqlite3.Connection) -> None:
    create_sql = read_sql(CREATE_SQL_PATH)
    import_sql = read_sql(IMPORT_SQL_PATH)
    conn.executescript(create_sql)
    conn.executescript(import_sql)


def fetch_all(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def fetch_value(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def build_demo_payload(
    conn: sqlite3.Connection,
    db_path: str,
    province: str,
    year: int,
) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row

    return {
        "db_path": db_path,
        "create_sql": str(CREATE_SQL_PATH),
        "import_sql": str(IMPORT_SQL_PATH),
        "table_exists": bool(
            fetch_value(
                conn,
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'admission_scores'",
            )
        ),
        "row_count": fetch_value(
            conn,
            "SELECT COUNT(*) FROM admission_scores",
        ),
        "province_count": fetch_value(
            conn,
            "SELECT COUNT(DISTINCT province) FROM admission_scores",
        ),
        "lookup": {
            "province": province,
            "year": year,
            "rows": fetch_all(
                conn,
                """
                SELECT *
                FROM admission_scores
                WHERE province = ? AND year = ?
                """,
                (province, year),
            ),
        },
        "province_history": fetch_all(
            conn,
            """
            SELECT
                province,
                year,
                admission_count,
                max_score,
                avg_score,
                min_score
            FROM admission_scores
            WHERE province = ?
            ORDER BY year DESC
            """,
            (province,),
        ),
        "sample_year_rows": fetch_all(
            conn,
            """
            SELECT
                province,
                year,
                admission_count,
                max_score,
                avg_score,
                min_score
            FROM admission_scores
            WHERE year = ?
            ORDER BY province
            LIMIT 5
            """,
            (year,),
        ),
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    db_path = resolve_db_path(args.db_path)
    if args.reset:
        reset_database_file(db_path)

    with sqlite3.connect(db_path) as conn:
        execute_scripts_on_connection(conn)
        payload = build_demo_payload(conn, db_path, args.province, args.year)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
