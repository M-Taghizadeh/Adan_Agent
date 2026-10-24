"""Hybrid sub-agent: multi-step reasoning with query_database + calculator tools."""

from __future__ import annotations

from typing import Any

from app.agents.sql_agent import result_to_dict
from app.agents.tool_agent import latest_ok, run_tool_loop
from app.config import get_settings
from app.sql.db import get_schema_description
from app.tools.calculator import calculator_tool
from app.tools.database import query_database

HYBRID_SYSTEM_PROMPT = """You are the data analyst for Adan Retail. The question needs numbers
from the sales database AND a calculation (percent, difference, ratio, average, ...).

Tools:
- query_database(sql): run ONE read-only SQLite SELECT.
- calculator(expression): evaluate math. Supports + - * / **, round, min, max, sqrt,
  avg(a, b, ...), pct(part, whole) = part as a percent of whole, and
  pct_change(new, old) = percent change from old to new.

Rules:
- First fetch the RAW numbers with query_database (you may call it several times, e.g. one
  query per region or per month). Do NOT compute the percentage/difference inside SQL.
- Then do ALL arithmetic with the calculator tool. Never calculate in your head.
- If a tool result has ok=false, read the error, fix your input and call the tool again
  (at most 3 retries per tool). If a query returns 0 rows, re-check filters and retry once.
- Every number in your answer must come from tool results.
- Final answer: 1-3 short sentences with the raw figures and the calculated result, and
  say the data came from the sales database. Reply in the language of the question.

{schema}
"""


def run_hybrid_agent(question: str, llm: Any | None = None) -> dict[str, Any]:
    run = run_tool_loop(
        question,
        tools=[query_database, calculator_tool],
        system_prompt=HYBRID_SYSTEM_PROMPT.format(schema=get_schema_description()),
        max_steps=get_settings().hybrid_agent_max_steps,
        llm=llm,
    )
    out = result_to_dict("hybrid_agent", run)
    calc = latest_ok(run.calls, "calculator")
    out["calculator"] = (
        {"expression": calc.parsed.get("expression"), "result": calc.parsed.get("result")}
        if calc and calc.parsed
        else None
    )
    return out
