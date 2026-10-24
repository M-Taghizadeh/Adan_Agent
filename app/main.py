"""FastAPI entrypoint for the Adan Retail assistant."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.coordinator import run_assistant
from app.config import get_settings
from app.llm import llm_is_configured
from app.models.schemas import AskRequest, AskResponse, HealthResponse
from app.rag.ingest import ensure_rag_ready
from app.sql.db import ensure_database
from app.sql.nl2sql import SQLSafetyError, execute_sql, validate_readonly_sql

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("Initializing database at %s", settings.db_path)
    ensure_database(force_reseed=False)
    logger.info("Initializing RAG index (may download embedding model on first run)...")
    ready = ensure_rag_ready(force_rebuild=False)
    if not ready:
        logger.warning("RAG index not ready — document questions may fail until fixed")
    yield


app = FastAPI(
    title="Adan Retail AI Assistant",
    description="RAG + NL2SQL + LangGraph coordinator with calculator tool",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    db_ready = settings.db_path.exists()
    rag_ready = (settings.faiss_index_dir / "index.faiss").exists()
    return HealthResponse(
        status="ok" if db_ready else "degraded",
        rag_ready=rag_ready,
        db_ready=db_ready,
        llm_configured=llm_is_configured(),
    )


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    try:
        return run_assistant(question, force_route=payload.force_route)
    except RuntimeError as exc:
        logger.exception("Assistant runtime error")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unhandled assistant error")
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}") from exc


@app.post("/sql/validate")
def validate_sql_endpoint(sql: str) -> dict:
    """Demo endpoint: shows how dangerous / invalid SQL is rejected (no LLM involved)."""
    try:
        validated = validate_readonly_sql(sql)
        rows = execute_sql(validated)
        return {"ok": True, "sql": validated, "result": rows}
    except SQLSafetyError as exc:
        return {"ok": False, "error": str(exc)}
