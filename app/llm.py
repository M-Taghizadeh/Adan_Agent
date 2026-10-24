"""Single place that builds the chat model (OpenAI or Gemini, both via ChatOpenAI)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI

from app.config import GEMINI_OPENAI_BASE_URL, Settings, get_settings


def _resolve(settings: Settings) -> tuple[str, str | None]:
    """Return (api_key, base_url) for the configured provider."""
    if settings.llm_provider == "gemini":
        key = settings.gemini_api_key or settings.openai_api_key
        base_url = settings.openai_base_url or GEMINI_OPENAI_BASE_URL
        return key, base_url
    return settings.openai_api_key, settings.openai_base_url or None


def llm_is_configured() -> bool:
    key, _ = _resolve(get_settings())
    return bool(key)


@lru_cache(maxsize=1)
def _build_llm() -> ChatOpenAI:
    settings = get_settings()
    key, base_url = _resolve(settings)
    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "api_key": key,
        "temperature": 0,
        "timeout": settings.llm_timeout,
        "max_retries": settings.llm_max_retries,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def get_llm() -> ChatOpenAI:
    """Chat model for agents. Raises RuntimeError when no API key is configured."""
    if not llm_is_configured():
        raise RuntimeError(
            "No LLM API key configured. Set OPENAI_API_KEY (or GEMINI_API_KEY with "
            "LLM_PROVIDER=gemini) in .env."
        )
    return _build_llm()
