"""Retrieval failures must surface as a controlled RuntimeError (API answers 503)."""

import pytest

from app.rag import retriever


def test_retrieval_failure_becomes_runtime_error(monkeypatch):
    def boom(question, top_k=None):
        raise FileNotFoundError("index missing")

    monkeypatch.setattr(retriever, "retrieve", boom)
    with pytest.raises(RuntimeError, match="retrieval failed"):
        retriever.answer_from_documents("any question")
