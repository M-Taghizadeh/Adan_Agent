"""Print top-1 cosine scores for in-scope vs out-of-scope questions and suggest RAG_MIN_SCORE.

Usage:  python scripts/check_rag_threshold.py
Needs the FAISS index (python scripts/build_index.py) and the embedding model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402

IN_SCOPE = [
    "How many days do customers have to return unused products?",
    "How many paid annual leave days do full-time employees get?",
    "What product categories are in the catalog?",
    "Can opened electronics be refunded?",
]
OUT_OF_SCOPE = [
    "What is the CEO salary and private phone number?",
    "Who won the football world cup?",
    "What is the capital of France?",
    "How do I cook rice?",
]


def top_score(question: str) -> float:
    hits = retrieve(question, top_k=1)
    return hits[0]["score"] if hits else -1.0


def main() -> None:
    print(f"Current RAG_MIN_SCORE = {get_settings().rag_min_score}\n")
    inside = [(q, top_score(q)) for q in IN_SCOPE]
    outside = [(q, top_score(q)) for q in OUT_OF_SCOPE]
    for label, rows in (("IN scope", inside), ("OUT of scope", outside)):
        print(label)
        for q, sc in rows:
            print(f"  {sc:6.3f}  {q}")
        print()
    low_in = min(sc for _, sc in inside)
    high_out = max(sc for _, sc in outside)
    if low_in > high_out:
        print(f"Clean gap. Suggested RAG_MIN_SCORE ~= {(low_in + high_out) / 2:.2f}")
    else:
        print(
            "Scores overlap (lowest in-scope %.3f <= highest out-of-scope %.3f): "
            "a threshold alone cannot separate them; rely on the LLM refusal prompt "
            "or add more/better documents." % (low_in, high_out)
        )


if __name__ == "__main__":
    main()
