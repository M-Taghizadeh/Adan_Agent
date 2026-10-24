from typing import Any, Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    force_route: Literal["auto", "rag", "sql", "hybrid"] | None = "auto"


class SourceCitation(BaseModel):
    document: str
    page: int | None = None
    chunk_id: str | None = None
    score: float | None = None
    excerpt: str | None = None


class TraceStep(BaseModel):
    component: str
    detail: str
    data: dict[str, Any] | None = None


class ToolCallRecord(BaseModel):
    """One tool call made by the LLM (query_database / calculator)."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    output: Any | None = None
    error: str | None = None


class AskResponse(BaseModel):
    answer: str
    route: str
    sources: list[SourceCitation] = Field(default_factory=list)
    sql: str | None = None
    sql_result: Any | None = None
    calculator: dict[str, Any] | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    insufficient_context: bool = False


class HealthResponse(BaseModel):
    status: str
    rag_ready: bool
    db_ready: bool
    llm_configured: bool
