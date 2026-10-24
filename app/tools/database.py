"""query_database tool exposed to the LLM (tool calling)."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from app.sql.nl2sql import run_query


@tool("query_database")
def query_database(sql: str) -> str:
    """Run ONE read-only SQLite SELECT on the Adan Retail database and return JSON.

    Success: {"ok": true, "sql": "...", "row_count": N, "rows": [...]}.
    Failure: {"ok": false, "error": "..."} - read the error, fix the query, call again.
    Only SELECT / WITH statements on the tables products and sales are allowed.
    """
    return json.dumps(run_query(sql), default=str, ensure_ascii=False)
