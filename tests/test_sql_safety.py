import sqlite3

import pytest

from app.sql.db import ensure_database, get_readonly_connection
from app.sql.nl2sql import (
    SQLSafetyError,
    execute_sql,
    run_query,
    validate_readonly_sql,
)


@pytest.fixture(scope="module", autouse=True)
def _db():
    ensure_database(force_reseed=True)


def test_allows_select_with_join_and_aggregation():
    sql = """
    SELECT p.category, SUM(s.quantity * s.unit_price) AS revenue
    FROM sales s
    JOIN products p ON p.product_id = s.product_id
    WHERE s.region = 'Tehran'
    GROUP BY p.category
    """
    rows = execute_sql(validate_readonly_sql(sql))
    assert len(rows) >= 1


def test_blocks_drop():
    with pytest.raises(SQLSafetyError, match="Forbidden"):
        validate_readonly_sql("DROP TABLE products")


def test_blocks_delete():
    with pytest.raises(SQLSafetyError, match="Forbidden"):
        validate_readonly_sql("DELETE FROM sales")


def test_blocks_multiple_statements():
    with pytest.raises(SQLSafetyError):
        validate_readonly_sql("SELECT 1; DROP TABLE sales")


def test_blocks_non_select():
    with pytest.raises(SQLSafetyError):
        validate_readonly_sql("EXPLAIN SELECT 1")


def test_filter_query_runs():
    rows = execute_sql(
        "SELECT name, stock_qty FROM products WHERE category = 'Electronics' "
        "ORDER BY stock_qty DESC"
    )
    assert len(rows) == 3


def test_replace_function_and_keyword_in_string_literal_are_allowed():
    sql = "SELECT REPLACE(name, 'Adan', 'A') AS n FROM products WHERE name LIKE '%update%'"
    assert validate_readonly_sql(sql) == sql
    assert execute_sql(sql) == []


def test_cte_with_count_runs():
    sql = (
        "WITH t AS (SELECT region, SUM(quantity * unit_price) AS rev FROM sales GROUP BY region) "
        "SELECT COUNT(*) AS n FROM t"
    )
    assert execute_sql(sql) == [{"n": 4}]


# --- layers below the validator: even if validation is bypassed, writes must fail -------
@pytest.mark.parametrize(
    "stmt",
    [
        "DELETE FROM sales",
        "DROP TABLE products",
        "INSERT INTO products VALUES (99, 'x', 'x', 'x', 1, 1)",
        "ATTACH DATABASE ':memory:' AS x",
        "PRAGMA query_only = OFF",
        "CREATE TABLE z (a)",
    ],
)
def test_readonly_connection_refuses_writes_without_validator(stmt):
    conn = get_readonly_connection()
    try:
        with pytest.raises(sqlite3.Error):
            conn.execute(stmt)
    finally:
        conn.close()


def test_cannot_read_sqlite_master():
    out = run_query("SELECT name FROM sqlite_master")
    assert out["ok"] is False


def test_runaway_query_is_interrupted():
    conn = get_readonly_connection(timeout_seconds=0.2)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) "
                "SELECT COUNT(*) FROM r"
            ).fetchall()
    finally:
        conn.close()


def test_row_cap_and_truncation_flag():
    out = run_query("SELECT * FROM sales", limit=5)
    assert out["ok"] and out["row_count"] == 5 and out["truncated"] is True


def test_run_query_reports_errors_instead_of_raising():
    bad = run_query("SELECT no_such_column FROM sales")
    assert bad["ok"] is False and "no such column" in bad["error"]
    empty = run_query("SELECT * FROM sales WHERE region = 'Nowhere'")
    assert empty["ok"] and empty["row_count"] == 0 and "0 rows" in empty["note"]
