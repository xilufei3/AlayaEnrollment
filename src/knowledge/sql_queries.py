from __future__ import annotations

from .sql_manager import SQLManager


def query_admission_scores(
    province: str | None = None,
    year: int | str | None = None,
    limit: int = 20,
) -> list[dict]:
    sql = """
    SELECT *
    FROM admission_scores
    WHERE (
        NULLIF(:province, '') IS NULL
        OR province LIKE '%' || :province || '%'
        OR :province LIKE '%' || province || '%'
    )
      AND (
        NULLIF(:year, '') IS NULL
        OR year = CAST(:year AS INTEGER)
      )
    LIMIT CAST(:limit AS INTEGER)
    """
    return SQLManager().execute(
        sql,
        params={
            "province": province,
            "year": year,
            "limit": limit,
        },
    )
