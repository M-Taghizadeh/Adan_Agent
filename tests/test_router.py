"""Router tests with a scripted LLM (no network / API key needed)."""

import pytest
from langchain_core.messages import AIMessage

from app.agents import coordinator
from app.agents.coordinator import route_node


def _state(question="q", force="auto"):
    return {"question": question, "force_route": force, "trace": []}


@pytest.mark.parametrize("reply, expected", [
    ("rag", "rag"),
    ("sql", "sql"),
    ("hybrid", "hybrid"),
    ("  HYBRID\n", "hybrid"),
    ("something unexpected", "rag"),  # unknown output falls back to the document route
])
def test_llm_reply_is_mapped_to_a_route(scripted, monkeypatch, reply, expected):
    llm = scripted([AIMessage(content=reply)])
    monkeypatch.setattr(coordinator, "get_llm", lambda: llm)
    out = route_node(_state("any question"))
    assert out["route"] == expected
    assert out["trace"][-1].detail == f"LLM route={expected}"
    assert llm.calls == 1


@pytest.mark.parametrize("forced", ["rag", "sql", "hybrid"])
def test_forced_route_skips_the_llm(monkeypatch, forced):
    def boom():
        raise AssertionError("LLM must not be called when force_route is set")

    monkeypatch.setattr(coordinator, "get_llm", boom)
    assert route_node(_state(force=forced))["route"] == forced


def test_missing_api_key_raises_instead_of_guessing(monkeypatch):
    def no_key():
        raise RuntimeError("No LLM API key configured.")

    monkeypatch.setattr(coordinator, "get_llm", no_key)
    with pytest.raises(RuntimeError, match="API key"):
        route_node(_state())


def test_router_llm_failure_becomes_runtime_error(scripted, monkeypatch):
    class Boom(scripted):
        def invoke(self, messages):
            raise ConnectionError("gateway down")

    monkeypatch.setattr(coordinator, "get_llm", lambda: Boom([]))
    with pytest.raises(RuntimeError, match="routing"):
        route_node(_state())
