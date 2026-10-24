"""Load PDFs, preprocess, embed, and persist a FAISS index."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from app.config import get_settings
from app.rag.preprocess import chunk_text, preprocess_page

logger = logging.getLogger(__name__)

_embeddings: HuggingFaceEmbeddings | None = None
_vectorstore: FAISS | None = None


def get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        settings = get_settings()
        _embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def load_and_preprocess_documents(documents_dir: Path) -> list[Document]:
    settings = get_settings()
    docs: list[Document] = []
    pdfs = sorted(documents_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {documents_dir}")

    for pdf_path in pdfs:
        loader = PyPDFLoader(str(pdf_path))
        pages = loader.load()
        for page in pages:
            page_num = int(page.metadata.get("page", 0)) + 1
            cleaned = preprocess_page(pdf_path.name, page_num, page.page_content)
            if cleaned is None:
                continue
            pieces = chunk_text(
                cleaned.text,
                chunk_size=settings.rag_chunk_size,
                overlap=settings.rag_chunk_overlap,
            )
            for idx, piece in enumerate(pieces):
                docs.append(
                    Document(
                        page_content=piece,
                        metadata={
                            "document": cleaned.document,
                            "page": cleaned.page,
                            "chunk_id": f"{cleaned.document}::p{cleaned.page}::c{idx}",
                            "source": str(pdf_path),
                        },
                    )
                )
    logger.info("Prepared %d chunks from %d PDFs", len(docs), len(pdfs))
    return docs


def build_or_load_vectorstore(force_rebuild: bool = False) -> FAISS:
    global _vectorstore
    if _vectorstore is not None and not force_rebuild:
        return _vectorstore

    settings = get_settings()
    index_dir = settings.faiss_index_dir
    embeddings = get_embeddings()

    if (index_dir / "index.faiss").exists() and not force_rebuild:
        logger.info("Loading FAISS index from %s", index_dir)
        _vectorstore = FAISS.load_local(
            str(index_dir),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        return _vectorstore

    documents_dir = settings.documents_dir
    docs = load_and_preprocess_documents(documents_dir)
    if not docs:
        raise RuntimeError("No document chunks available after preprocessing")

    logger.info("Building FAISS index (%d chunks)...", len(docs))
    store = FAISS.from_documents(docs, embeddings)
    index_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(index_dir))
    _vectorstore = store
    return store


def ensure_rag_ready(force_rebuild: bool = False) -> bool:
    try:
        build_or_load_vectorstore(force_rebuild=force_rebuild)
        return True
    except Exception:
        logger.exception("RAG initialization failed")
        return False
