"""Document-focused sub-agent."""

from __future__ import annotations

from typing import Any

from app.rag.retriever import answer_from_documents


def run_rag_agent(question: str) -> dict[str, Any]:
    result = answer_from_documents(question)
    return {
        "component": "rag_agent",
        "answer": result["answer"],
        "sources": result["sources"],
        "insufficient_context": result["insufficient_context"],
        "retrieved_count": len(result.get("retrieved") or []),
    }
