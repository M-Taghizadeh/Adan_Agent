"""SQL validation + safe execution for LLM-generated queries.

Defense in depth (any one layer alone is enough to stop a write):
  1. validate_readonly_sql  - single SELECT/WITH statement, no DDL/DML keywords
  2. read-only connection   - file opened with mode=ro and PRAGMA query_only
  3. sqlite authorizer      - only SELECT + reads of products/sales are allowed
  4. progress handler       - statement is aborted after sql_timeout_seconds
  5. row cap                - at most `limit` rows are fetched
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

import sqlparse

from app.config import get_settings
from app.sql.db import get_readonly_connection

logger = logging.getLogger(__name__)

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "VACUUM",
    "REINDEX",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


class SQLSafetyError(ValueError):
    pass


def validate_readonly_sql(sql: str) -> str:
    """Ensure the statement is a single read-only SELECT (optionally WITH ... SELECT)."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SQLSafetyError("Empty SQL")

    # Look only at code: drop comments and string literals ('...update...' is fine).
    code = sqlparse.format(cleaned, strip_comments=True)
    code = _STRING_LITERAL_RE.sub("''", code).strip()

    if ";" in code:
        raise SQLSafetyError("Multiple statements are not allowed")

    forbidden = _FORBIDDEN_RE.search(code)
    if forbidden:
        raise SQLSafetyError(f"Forbidden keyword detected: {forbidden.group(1).upper()}")

    if not re.match(r"(SELECT|WITH)\b", code, re.IGNORECASE):
        raise SQLSafetyError("Only SELECT / WITH queries are permitted")

    if len(sqlparse.parse(cleaned)) != 1:
        raise SQLSafetyError("Only a single SQL statement is allowed")

    return cleaned


def _execute(sql: str, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Validate and run `sql`; return (rows, truncated)."""
    safe_sql = validate_readonly_sql(sql)
    conn = get_readonly_connection()
    try:
        cur = conn.execute(safe_sql)
        fetched = cur.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        return [dict(row) for row in fetched[:limit]], truncated
    except sqlite3.Error as exc:
        raise SQLSafetyError(f"SQL execution failed: {exc}") from exc
    finally:
        conn.close()


def execute_sql(sql: str, limit: int | None = None) -> list[dict[str, Any]]:
    rows, _ = _execute(sql, limit or get_settings().sql_max_rows)
    return rows


def run_query(sql: str, limit: int | None = None) -> dict[str, Any]:
    """Tool-friendly wrapper: never raises, returns {ok, sql, rows...} or {ok: False, error}."""
    max_rows = limit or get_settings().sql_max_rows
    candidate = (sql or "").strip().rstrip(";").strip()
    try:
        rows, truncated = _execute(candidate, max_rows)
    except SQLSafetyError as exc:
        return {"ok": False, "sql": candidate, "error": str(exc)}
    out: dict[str, Any] = {
        "ok": True,
        "sql": candidate,
        "row_count": len(rows),
        "rows": rows,
    }
    if truncated:
        out["truncated"] = True
        out["note"] = f"Only the first {max_rows} rows are returned."
    if not rows:
        out["note"] = "Query returned 0 rows. Check filters (region/category spelling, dates)."
    return out
