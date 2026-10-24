"""SQLite database bootstrap and schema helpers for Adan Retail."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.config import get_settings

# Tables the read-only (LLM-facing) connection may read.
ALLOWED_TABLES = frozenset({"products", "sales"})

# sqlite3 authorizer action codes (numeric so this works on every Python version).
_SQLITE_OK, _SQLITE_DENY = 0, 1
_ACTION_READ = 20
_ACTION_SELECT = 21
_ACTION_FUNCTION = 31
_ACTION_RECURSIVE = 33

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price REAL NOT NULL,
    stock_qty INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    sale_date TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    region TEXT NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
"""

SEED_SQL = """
DELETE FROM sales;
DELETE FROM products;

INSERT INTO products (product_id, sku, name, category, unit_price, stock_qty) VALUES
(1, 'ADN-KB-01', 'Adan Mechanical Keyboard', 'Electronics', 89.99, 120),
(2, 'ADN-MS-02', 'Adan Wireless Mouse', 'Electronics', 34.50, 250),
(3, 'ADN-HD-03', 'Adan Noise-Cancel Headset', 'Electronics', 129.00, 80),
(4, 'ADN-NB-04', 'Adan Notebook A5', 'Stationery', 6.75, 500),
(5, 'ADN-PN-05', 'Adan Gel Pen Pack', 'Stationery', 4.20, 800),
(6, 'ADN-BG-06', 'Adan Laptop Backpack', 'Accessories', 59.00, 95);

INSERT INTO sales (sale_id, product_id, sale_date, quantity, unit_price, region) VALUES
(1, 1, '2025-01-05', 3, 89.99, 'Tehran'),
(2, 1, '2025-01-12', 2, 89.99, 'Isfahan'),
(3, 2, '2025-01-08', 10, 34.50, 'Tehran'),
(4, 2, '2025-01-20', 5, 34.50, 'Shiraz'),
(5, 3, '2025-01-15', 4, 129.00, 'Tehran'),
(6, 3, '2025-02-01', 2, 129.00, 'Mashhad'),
(7, 4, '2025-01-10', 40, 6.75, 'Tehran'),
(8, 4, '2025-02-05', 25, 6.75, 'Isfahan'),
(9, 5, '2025-01-18', 60, 4.20, 'Tehran'),
(10, 5, '2025-02-10', 30, 4.20, 'Shiraz'),
(11, 6, '2025-01-22', 6, 59.00, 'Tehran'),
(12, 6, '2025-02-14', 3, 59.00, 'Isfahan'),
(13, 1, '2025-02-18', 5, 89.99, 'Tehran'),
(14, 3, '2025-02-20', 1, 129.00, 'Shiraz'),
(15, 2, '2025-03-01', 8, 34.50, 'Tehran');
"""

SCHEMA_DESCRIPTION = """
Database: Adan Retail (SQLite)

Table products:
  - product_id (INTEGER, PK)
  - sku (TEXT): product code, e.g. ADN-KB-01
  - name (TEXT): product display name
  - category (TEXT): Electronics | Stationery | Accessories
  - unit_price (REAL): list price in USD
  - stock_qty (INTEGER): current warehouse stock

Table sales:
  - sale_id (INTEGER, PK)
  - product_id (INTEGER, FK -> products.product_id)
  - sale_date (TEXT, ISO date YYYY-MM-DD)
  - quantity (INTEGER): units sold
  - unit_price (REAL): price at time of sale
  - region (TEXT): Tehran | Isfahan | Shiraz | Mashhad

Notes:
  - Revenue for a sale line = quantity * unit_price
  - Prefer JOINs via products.product_id = sales.product_id
  - Dates are TEXT; compare with string literals like '2025-02-01'
"""


def ensure_database(db_path: Path | None = None, force_reseed: bool = False) -> Path:
    settings = get_settings()
    path = Path(db_path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    needs_seed = force_reseed or not path.exists()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        if needs_seed:
            # If file existed but empty tables, still seed when forced or empty.
            cur = conn.execute("SELECT COUNT(*) FROM products")
            count = cur.fetchone()[0]
            if force_reseed or count == 0:
                conn.executescript(SEED_SQL)
        conn.commit()
    finally:
        conn.close()
    return path


_SYSTEM_TABLES = frozenset(
    {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}
)


def _make_authorizer(blocked_tables: frozenset[str]):
    """Allow SELECT, function calls and recursive CTEs; deny reads of blocked tables.

    CTE names are not real tables, so reading them is fine; only real tables that are
    not in ALLOWED_TABLES (and sqlite_master) are blocked. Everything else is denied.
    """

    def authorizer(action: int, arg1, arg2, dbname, source) -> int:
        if action in (_ACTION_SELECT, _ACTION_FUNCTION, _ACTION_RECURSIVE):
            return _SQLITE_OK
        if action == _ACTION_READ:
            if arg1 and str(arg1).lower() in blocked_tables:
                return _SQLITE_DENY
            return _SQLITE_OK
        return _SQLITE_DENY

    return authorizer


def get_readonly_connection(
    db_path: Path | None = None, timeout_seconds: float | None = None
) -> sqlite3.Connection:
    """Connection for LLM-generated SQL: read-only file, query_only, authorizer, timeout."""
    settings = get_settings()
    path = Path(db_path or settings.db_path)
    if not path.exists():
        ensure_database(path)

    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")  # must run before the authorizer is installed
    real_objects = {row[0].lower() for row in conn.execute("SELECT name FROM sqlite_master")}
    blocked = frozenset((real_objects | _SYSTEM_TABLES) - ALLOWED_TABLES)
    conn.set_authorizer(_make_authorizer(blocked))

    limit = timeout_seconds if timeout_seconds is not None else settings.sql_timeout_seconds
    deadline = time.monotonic() + limit
    # Returning non-zero aborts the running statement (-> sqlite3.OperationalError).
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    return conn


def get_schema_description() -> str:
    return SCHEMA_DESCRIPTION.strip()
