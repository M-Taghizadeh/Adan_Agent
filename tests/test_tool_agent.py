"""Tool-calling agents tested with a scripted LLM (no network / API key needed)."""

import json

import pytest
from langchain_core.messages import AIMessage

from app.agents import coordinator
from app.agents.hybrid_agent import run_hybrid_agent
from app.agents.sql_agent import run_sql_agent
from app.agents.tool_agent import run_tool_loop
from app.sql.db import ensure_database
from app.tools.calculator import calculator_tool
from app.tools.database import query_database
from tests.conftest import ScriptedLLM, tool_call


@pytest.fixture(scope="module", autouse=True)
def _db():
    ensure_database(force_reseed=True)


def test_sql_agent_runs_query_and_returns_final_answer():
    llm = ScriptedLLM(
        [
            tool_call("query_database", {"sql": "SELECT SUM(quantity*unit_price) AS total FROM sales"}),
            AIMessage(content="Total revenue is 3944.15 (from the sales database)."),
        ]
    )
    out = run_sql_agent("What is the total revenue?", llm=llm)
    assert out["sql"].startswith("SELECT SUM")
    assert out["sql_result"] == [{"total": 3944.15}]
    assert "3944.15" in out["answer"]
    assert [c.tool for c in out["calls"]] == ["query_database"]


def test_agent_recovers_from_sql_error_by_retrying():
    llm = ScriptedLLM(
        [
            tool_call("query_database", {"sql": "SELECT SUM(amount) FROM sales"}, "c1"),
            tool_call("query_database", {"sql": "SELECT SUM(quantity*unit_price) AS total FROM sales"}, "c2"),
            AIMessage(content="Total revenue is 3944.15."),
        ]
    )
    out = run_sql_agent("Total revenue?", llm=llm)
    assert [c.ok for c in out["calls"]] == [False, True]
    assert "no such column" in out["calls"][0].error
    assert out["sql_result"] == [{"total": 3944.15}]
    assert out["error"] is None


def test_hybrid_agent_chains_sql_then_calculator():
    llm = ScriptedLLM(
        [
            tool_call("query_database", {"sql": "SELECT SUM(quantity*unit_price) AS total FROM sales"}, "c1"),
            tool_call("calculator", {"expression": "3944.15 * 15 / 100"}, "c2"),
            AIMessage(content="Revenue is 3944.15; 15% of it is 591.6225."),
        ]
    )
    out = run_hybrid_agent("Total revenue and 15 percent of it?", llm=llm)
    assert [c.tool for c in out["calls"]] == ["query_database", "calculator"]
    assert out["calculator"] == {"expression": "3944.15 * 15 / 100", "result": 591.6225}
    assert out["sql_result"] == [{"total": 3944.15}]


def test_hybrid_agent_multiple_queries_then_difference():
    llm = ScriptedLLM(
        [
            tool_call("query_database", {"sql": "SELECT SUM(quantity*unit_price) AS r FROM sales WHERE region='Tehran'"}, "c1"),
            tool_call("query_database", {"sql": "SELECT SUM(quantity*unit_price) AS r FROM sales WHERE region='Isfahan'"}, "c2"),
            tool_call("calculator", {"expression": "pct_change(2000, 1000)"}, "c3"),
            AIMessage(content="Tehran is 100% above Isfahan."),
        ]
    )
    out = run_hybrid_agent("How much more is Tehran than Isfahan, in percent?", llm=llm)
    assert len(out["calls"]) == 3
    assert out["calculator"]["result"] == 100.0


def test_calculator_error_is_returned_to_llm_not_raised():
    assert json.loads(calculator_tool.invoke({"expression": "pct(1)"}))["ok"] is False
    assert json.loads(calculator_tool.invoke({"expression": "__import__('os')"}))["ok"] is False


def test_unknown_tool_does_not_crash_the_loop():
    llm = ScriptedLLM([tool_call("rm_rf", {"x": 1}), AIMessage(content="Sorry, cannot do that.")])
    run = run_tool_loop("hi", [query_database], "sys", max_steps=3, llm=llm)
    assert run.calls[0].ok is False and "Unknown tool" in run.calls[0].error


def test_step_limit_forces_a_final_answer():
    endless = [tool_call("query_database", {"sql": "SELECT 1"}, f"c{i}") for i in range(2)]
    llm = ScriptedLLM(endless + [AIMessage(content="Best effort answer.")])
    run = run_tool_loop("q", [query_database], "sys", max_steps=2, llm=llm)
    assert run.hit_step_limit is True
    assert run.answer == "Best effort answer."
    assert len(run.calls) == 2


def test_llm_failure_becomes_runtime_error():
    class Boom(ScriptedLLM):
        def invoke(self, messages):
            raise ConnectionError("gateway down")

    with pytest.raises(RuntimeError, match="LLM call failed"):
        run_tool_loop("q", [query_database], "sys", max_steps=2, llm=Boom([]))


def test_end_to_end_hybrid_response_fields(monkeypatch):
    llm = ScriptedLLM(
        [
            tool_call("query_database", {"sql": "SELECT SUM(quantity*unit_price) AS total FROM sales"}, "c1"),
            tool_call("calculator", {"expression": "pct(591.6225, 3944.15)"}, "c2"),
            AIMessage(content="15% of 3944.15 is 591.62."),
        ]
    )
    monkeypatch.setattr("app.agents.tool_agent.get_llm", lambda: llm)
    coordinator.reset_graph()
    res = coordinator.run_assistant("Total revenue and calculate 15 percent", force_route="hybrid")
    assert res.route == "hybrid"
    assert res.sql and res.sql_result == [{"total": 3944.15}]
    assert res.calculator["result"] == 15.0
    assert [t.tool for t in res.tool_calls] == ["query_database", "calculator"]
    components = [t.component for t in res.trace]
    assert components[:2] == ["coordinator", "hybrid_agent"]
    assert "query_database" in components and "calculator" in components
