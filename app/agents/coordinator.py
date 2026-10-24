"""LangGraph coordinator: an LLM router picks RAG, SQL, or hybrid (SQL + calculator)."""

from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.hybrid_agent import run_hybrid_agent
from app.agents.rag_agent import run_rag_agent
from app.agents.sql_agent import run_sql_agent
from app.agents.tool_agent import message_text
from app.llm import get_llm
from app.models.schemas import AskResponse, SourceCitation, ToolCallRecord, TraceStep

logger = logging.getLogger(__name__)

Route = Literal["rag", "sql", "hybrid"]


class AgentState(TypedDict, total=False):
    question: str
    force_route: str | None
    route: Route
    rag: dict[str, Any]
    sql: dict[str, Any]
    calculator: dict[str, Any] | None
    tool_calls: list[ToolCallRecord]
    answer: str
    sources: list[SourceCitation]
    insufficient_context: bool
    trace: list[TraceStep]
    error: str | None


# --------------------------------------------------------------------------- routing
ROUTER_SYSTEM_PROMPT = (
    "You are a router for Adan Retail assistant.\n"
    "Choose exactly one route:\n"
    "- rag: questions about policies, handbook, catalog text documents\n"
    "- sql: questions needing numbers from the sales/products database "
    "(aggregations, filters, joins)\n"
    "- hybrid: needs a DB number AND a calculation "
    "(percent, difference, ratio, etc.)\n"
    "Reply with only one word: rag | sql | hybrid"
)


def route_node(state: AgentState) -> AgentState:
    """Pick the route: a valid `force_route` wins, otherwise ask the LLM.

    No keyword fallback: if there is no API key or the LLM call fails, a RuntimeError
    propagates and the API answers 503 instead of silently guessing a route.
    """
    force = (state.get("force_route") or "auto").lower()
    trace = list(state.get("trace") or [])

    if force in {"rag", "sql", "hybrid"}:
        route: Route = force  # type: ignore[assignment]
        trace.append(TraceStep(component="coordinator", detail=f"Forced route={route}"))
        return {**state, "route": route, "trace": trace}

    llm = get_llm()  # raises RuntimeError when no API key is configured
    try:
        response = llm.invoke(
            [SystemMessage(content=ROUTER_SYSTEM_PROMPT), HumanMessage(content=state["question"])]
        )
    except Exception as exc:
        logger.exception("Router LLM call failed")
        raise RuntimeError(f"LLM call failed during routing: {exc}") from exc

    raw = message_text(response.content).lower()
    if "hybrid" in raw:
        route = "hybrid"
    elif "sql" in raw:
        route = "sql"
    else:
        route = "rag"
    trace.append(
        TraceStep(component="coordinator", detail=f"LLM route={route}", data={"raw": raw})
    )
    return {**state, "route": route, "trace": trace}


# --------------------------------------------------------------------------- helpers
def _tool_records(calls: list[Any]) -> list[ToolCallRecord]:
    return [
        ToolCallRecord(
            tool=c.tool,
            arguments=c.arguments,
            ok=c.ok,
            output=c.parsed if c.parsed is not None else c.output,
            error=c.error,
        )
        for c in calls
    ]


def _agent_trace(component: str, result: dict[str, Any]) -> list[TraceStep]:
    """One summary step for the agent, then one step per tool the LLM called."""
    calls = result.get("calls") or []
    steps = [
        TraceStep(
            component=component,
            detail=f"Tool-calling agent: {result.get('steps')} LLM step(s), "
            f"{len(calls)} tool call(s)",
            data={
                "tools": [c.tool for c in calls],
                "hit_step_limit": result.get("hit_step_limit"),
            },
        )
    ]
    for i, c in enumerate(calls, start=1):
        data: dict[str, Any] = {"arguments": c.arguments, "ok": c.ok}
        if c.tool == "query_database" and c.parsed:
            data["row_count"] = c.parsed.get("row_count")
        if c.tool == "calculator" and c.parsed:
            data["result"] = c.parsed.get("result")
        if c.error:
            data["error"] = c.error
        steps.append(TraceStep(component=c.tool, detail=f"Tool call #{i}", data=data))
    return steps


# --------------------------------------------------------------------------- nodes
def rag_node(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    result = run_rag_agent(state["question"])
    trace.append(
        TraceStep(
            component="rag_agent",
            detail="Retrieved documents and generated grounded answer",
            data={
                "insufficient_context": result.get("insufficient_context"),
                "retrieved_count": result.get("retrieved_count"),
            },
        )
    )
    return {
        **state,
        "rag": result,
        "answer": result["answer"],
        "sources": result.get("sources") or [],
        "insufficient_context": bool(result.get("insufficient_context")),
        "trace": trace,
    }


def sql_node(state: AgentState) -> AgentState:
    result = run_sql_agent(state["question"])
    trace = list(state.get("trace") or []) + _agent_trace("sql_agent", result)
    return {
        **state,
        "sql": result,
        "calculator": None,
        "tool_calls": _tool_records(result.get("calls") or []),
        "answer": result["answer"],
        "sources": [],
        "trace": trace,
    }


def hybrid_node(state: AgentState) -> AgentState:
    """Multi-step: the LLM chains query_database and calculator tool calls itself."""
    result = run_hybrid_agent(state["question"])
    trace = list(state.get("trace") or []) + _agent_trace("hybrid_agent", result)
    return {
        **state,
        "sql": result,
        "calculator": result.get("calculator"),
        "tool_calls": _tool_records(result.get("calls") or []),
        "answer": result["answer"],
        "sources": [],
        "trace": trace,
    }


def _dispatch(state: AgentState) -> str:
    """Map selected route to graph node names (must not collide with state keys)."""
    chosen = state.get("route") or "rag"
    return {"rag": "rag_agent", "sql": "sql_agent", "hybrid": "hybrid_agent"}.get(
        chosen, "rag_agent"
    )


def build_graph():
    graph = StateGraph(AgentState)
    # Node names must differ from AgentState keys (route/rag/sql/...).
    graph.add_node("router", route_node)
    graph.add_node("rag_agent", rag_node)
    graph.add_node("sql_agent", sql_node)
    graph.add_node("hybrid_agent", hybrid_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        _dispatch,
        {
            "rag_agent": "rag_agent",
            "sql_agent": "sql_agent",
            "hybrid_agent": "hybrid_agent",
        },
    )
    graph.add_edge("rag_agent", END)
    graph.add_edge("sql_agent", END)
    graph.add_edge("hybrid_agent", END)
    return graph.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def reset_graph() -> None:
    """Clear cached graph (useful after code reload / tests)."""
    global _GRAPH
    _GRAPH = None


def run_assistant(question: str, force_route: str | None = "auto") -> AskResponse:
    graph = get_graph()
    initial: AgentState = {
        "question": question.strip(),
        "force_route": force_route,
        "trace": [],
        "sources": [],
        "tool_calls": [],
        "insufficient_context": False,
    }
    final: AgentState = graph.invoke(initial)

    sql_payload = final.get("sql") or {}
    return AskResponse(
        answer=final.get("answer") or "No answer produced.",
        route=final.get("route") or "unknown",
        sources=final.get("sources") or [],
        sql=sql_payload.get("sql"),
        sql_result=sql_payload.get("sql_result"),
        calculator=final.get("calculator"),
        tool_calls=final.get("tool_calls") or [],
        trace=final.get("trace") or [],
        insufficient_context=bool(final.get("insufficient_context")),
    )
