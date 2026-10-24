"""Generic tool-calling loop shared by the SQL and hybrid agents.

The LLM decides which tool to call (query_database, calculator), sees each tool's
JSON result - including errors - and can fix its own mistakes (e.g. a bad SQL query)
before giving the final answer. The loop is bounded by `max_steps`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.llm import get_llm

logger = logging.getLogger(__name__)

STEP_LIMIT_NUDGE = (
    "Step limit reached. Using ONLY the tool results above, give the final answer now. "
    "Do not call any more tools. If the data was not obtained, say so."
)


@dataclass
class ToolCallResult:
    tool: str
    arguments: dict[str, Any]
    output: str
    parsed: dict[str, Any] | None
    ok: bool
    error: str | None


@dataclass
class AgentRun:
    answer: str
    calls: list[ToolCallResult]
    steps: int
    hit_step_limit: bool


def message_text(content: Any) -> str:
    """Normalize an LLM message content (str or list of blocks) to plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()


def _parse(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _invoke_tool(tools_by_name: dict[str, Any], name: str, args: dict[str, Any]) -> str:
    tool = tools_by_name.get(name)
    if tool is None:
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})
    try:
        return str(tool.invoke(args))
    except Exception as exc:  # tool bugs must not crash the whole request
        logger.exception("Tool %s failed", name)
        return json.dumps({"ok": False, "error": f"Tool error: {exc}"})


def run_tool_loop(
    question: str,
    tools: list[Any],
    system_prompt: str,
    max_steps: int,
    llm: Any | None = None,
) -> AgentRun:
    base_llm = llm if llm is not None else get_llm()
    llm_with_tools = base_llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    messages: list[Any] = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    calls: list[ToolCallResult] = []
    steps = 0

    def call_llm(model: Any) -> Any:
        nonlocal steps
        steps += 1
        try:
            return model.invoke(messages)
        except Exception as exc:
            logger.exception("LLM call failed")
            raise RuntimeError(f"LLM call failed: {exc}") from exc

    for _ in range(max_steps):
        ai = call_llm(llm_with_tools)
        messages.append(ai)
        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            answer = message_text(ai.content) or "The model returned an empty answer."
            return AgentRun(answer=answer, calls=calls, steps=steps, hit_step_limit=False)

        for tc in tool_calls:
            name, args = tc["name"], tc.get("args") or {}
            output = _invoke_tool(tools_by_name, name, args)
            parsed = _parse(output)
            ok = bool(parsed.get("ok", True)) if parsed is not None else True
            error = str(parsed.get("error")) if parsed is not None and not ok else None
            calls.append(ToolCallResult(name, args, output, parsed, ok, error))
            messages.append(ToolMessage(content=output, tool_call_id=tc["id"], name=name))

    # Step budget exhausted: force a final answer from what we have (no tools bound).
    messages.append(HumanMessage(content=STEP_LIMIT_NUDGE))
    ai = call_llm(base_llm)
    answer = message_text(ai.content) or "I could not finish within the step limit."
    return AgentRun(answer=answer, calls=calls, steps=steps, hit_step_limit=True)


def latest_ok(calls: list[ToolCallResult], tool: str) -> ToolCallResult | None:
    for call in reversed(calls):
        if call.tool == tool and call.ok:
            return call
    return None


def latest_error(calls: list[ToolCallResult]) -> str | None:
    for call in reversed(calls):
        if not call.ok:
            return call.error
    return None


def sql_summary(run: AgentRun) -> dict[str, Any]:
    """sql / sql_result / row_count / error fields for API responses."""
    ok = latest_ok(run.calls, "query_database")
    if ok and ok.parsed:
        return {
            "sql": ok.parsed.get("sql"),
            "sql_result": ok.parsed.get("rows"),
            "row_count": ok.parsed.get("row_count"),
            "error": None,
        }
    return {"sql": None, "sql_result": None, "row_count": None, "error": latest_error(run.calls)}
