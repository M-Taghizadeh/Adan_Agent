"""Create and seed the Adan Retail SQLite database."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sql.db import ensure_database  # noqa: E402


def main() -> None:
    path = ensure_database(force_reseed=True)
    print(f"Database ready at {path}")


if __name__ == "__main__":
    main()
