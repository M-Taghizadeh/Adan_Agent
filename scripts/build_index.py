"""Build the FAISS vector index from sample PDFs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.rag.ingest import build_or_load_vectorstore  # noqa: E402


def main() -> None:
    store = build_or_load_vectorstore(force_rebuild=True)
    print(f"FAISS index built with {store.index.ntotal} vectors")


if __name__ == "__main__":
    main()
