from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent

# Google's OpenAI-compatible endpoint (verify against Google's current docs).
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM -----------------------------------------------------------------
    llm_provider: Literal["openai", "gemini"] = "openai"
    openai_api_key: str = ""
    openai_base_url: str | None = None
    gemini_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0
    llm_max_retries: int = 2

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    documents_dir: Path = ROOT_DIR / "data" / "documents"
    faiss_index_dir: Path = ROOT_DIR / "data" / "faiss_index"
    db_path: Path = ROOT_DIR / "data" / "db" / "adan_retail.db"

    # --- RAG -----------------------------------------------------------------
    rag_top_k: int = 4
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 80
    # Cosine similarity threshold (-1..1). Calibrate with scripts/check_rag_threshold.py
    rag_min_score: float = 0.30

    # --- SQL / agents --------------------------------------------------------
    sql_max_rows: int = 50
    sql_timeout_seconds: float = 5.0
    sql_agent_max_steps: int = 6
    hybrid_agent_max_steps: int = 8

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
