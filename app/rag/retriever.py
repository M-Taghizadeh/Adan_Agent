"""Semantic retrieval + grounded LLM answers with source citations."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.llm import get_llm
from app.models.schemas import SourceCitation
from app.rag.ingest import build_or_load_vectorstore

logger = logging.getLogger(__name__)


def retrieve(question: str, top_k: int | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    k = top_k or settings.rag_top_k
    store = build_or_load_vectorstore()
    # FAISS (IndexFlatL2) returns the SQUARED L2 distance. Embeddings are normalized
    # (unit length), so d = 2 - 2*cos  =>  cosine similarity = 1 - d/2  (range -1..1).
    pairs = store.similarity_search_with_score(question, k=k)
    results: list[dict[str, Any]] = []
    for doc, distance in pairs:
        sim = max(-1.0, min(1.0, 1.0 - float(distance) / 2.0))
        results.append(
            {
                "content": doc.page_content,
                "document": doc.metadata.get("document", "unknown"),
                "page": doc.metadata.get("page"),
                "chunk_id": doc.metadata.get("chunk_id"),
                "score": round(sim, 4),
                "distance": float(distance),
            }
        )
    return results


def answer_from_documents(question: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        hits = retrieve(question)
    except Exception as exc:
        logger.exception("Document retrieval failed")
        raise RuntimeError(f"Document retrieval failed: {exc}") from exc
    strong = [h for h in hits if h["score"] >= settings.rag_min_score]

    sources = [
        SourceCitation(
            document=h["document"],
            page=h["page"],
            chunk_id=h["chunk_id"],
            score=h["score"],
            excerpt=h["content"][:240],
        )
        for h in (strong or hits)[: settings.rag_top_k]
    ]

    if not strong:
        return {
            "answer": (
                "I could not find enough information in the company documents "
                "to answer this question reliably. Please rephrase or ask about "
                "return policy, employee leave, or product catalog topics covered "
                "in the sample PDFs."
            ),
            "sources": sources,
            "insufficient_context": True,
            "retrieved": hits,
        }

    context_blocks = []
    for i, h in enumerate(strong, start=1):
        context_blocks.append(
            f"[{i}] ({h['document']} p.{h['page']})\n{h['content']}"
        )
    context = "\n\n".join(context_blocks)

    llm = get_llm()
    system = SystemMessage(
        content=(
            "You are the Adan Retail internal document assistant.\n"
            "Answer ONLY using the provided context excerpts.\n"
            "If the context is insufficient, say so clearly — do not invent facts.\n"
            "Cite sources inline like [1], [2] matching the excerpt numbers.\n"
            "Be concise and practical."
        )
    )
    human = HumanMessage(
        content=f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    )
    try:
        response = llm.invoke([system, human])
        answer = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
    except Exception as exc:
        logger.exception("RAG LLM call failed")
        raise RuntimeError(f"LLM call failed during RAG: {exc}") from exc

    return {
        "answer": answer.strip(),
        "sources": sources,
        "insufficient_context": False,
        "retrieved": hits,
    }
