import pytest
from langchain_core.messages import AIMessage


class ScriptedLLM:
    """Stand-in chat model: returns pre-written AIMessages, one per invoke()."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        return self.script.pop(0)


def tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


@pytest.fixture
def scripted():
    return ScriptedLLM
