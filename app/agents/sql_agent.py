"""Database sub-agent: LLM writes SQL via the query_database tool (NL2SQL)."""

from __future__ import annotations

from typing import Any

from app.agents.tool_agent import AgentRun, run_tool_loop, sql_summary
from app.config import get_settings
from app.sql.db import get_schema_description
from app.tools.database import query_database

SQL_SYSTEM_PROMPT = """You are the data analyst for Adan Retail. Answer using the sales database.

You have one tool: query_database(sql). Rules:
- Write ONE read-only SQLite SELECT per call, using only the tables/columns below.
- If a tool result has ok=false, read the error, fix the query and call the tool again
  (at most 3 attempts). If a result has 0 rows although you expected data, re-check
  the filters (exact region/category spelling, date format) and retry once.
- Every number in your answer must come from tool results. Never guess or invent data.
- Final answer: 1-3 short sentences for a business user, with the key numbers, and say
  the answer came from the sales database. If the schema cannot answer the question,
  say so plainly. Reply in the language of the question.

{schema}
"""


def build_sql_prompt() -> str:
    return SQL_SYSTEM_PROMPT.format(schema=get_schema_description())


def result_to_dict(component: str, run: AgentRun) -> dict[str, Any]:
    return {
        "component": component,
        "answer": run.answer,
        "calls": run.calls,
        "steps": run.steps,
        "hit_step_limit": run.hit_step_limit,
        **sql_summary(run),
    }


def run_sql_agent(question: str, llm: Any | None = None) -> dict[str, Any]:
    run = run_tool_loop(
        question,
        tools=[query_database],
        system_prompt=build_sql_prompt(),
        max_steps=get_settings().sql_agent_max_steps,
        llm=llm,
    )
    return result_to_dict("sql_agent", run)
