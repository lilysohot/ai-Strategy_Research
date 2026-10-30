"""Per-request schema restrictions remain isolated from other loop bindings."""
from types import SimpleNamespace

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import Intervention, LoopConfig, merge_interventions
from frontier_agent.core.runtime.loop._bind import bind_tools, restrict_tools
from frontier_agent.core.runtime.loop.agent_loop import _prepare_llm_request


def schema(name):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_multiple_tool_restrictions_intersect_without_widening():
    merged = merge_interventions([
        Intervention(allowed_tool_names=("search", "submit")),
        Intervention(inject_messages=["finish"]),
        Intervention(allowed_tool_names=("publish", "submit")),
    ])
    assert merged.allowed_tool_names == ("submit",)
    assert merged.inject_messages == ["finish"]
    assert merge_interventions([merged, Intervention(allowed_tool_names=())]).allowed_tool_names == ()
    assert merge_interventions([Intervention()]).allowed_tool_names is None


@pytest.mark.asyncio
async def test_tool_restrictions_do_not_leak_and_empty_overrides_nested_binding():
    class Client:
        model = "scripted"
        def __init__(self):
            self.seen = []

        async def chat(self, messages, **kwargs):
            self.seen.append(kwargs["tools"])
            return LLMResponse(content="ok")

        def stream(self, messages, **kwargs):
            self.seen.append(kwargs["tools"])
            return "stream"

    client = Client()
    tools = [schema("search"), schema("submit")]
    bound = bind_tools(client, tools)
    restricted = restrict_tools(bound, ("submit",))
    await restricted.chat([])
    restricted.stream([])
    await bound.chat([])
    # Wrap an already-bound client as happens through middleware; an empty
    # selection must be explicit, not revive the inner client's old tools.
    from frontier_agent.core.runtime.loop._bind import _BoundLLM
    nested = _BoundLLM(client=bound, tools=tools)
    await restrict_tools(nested, ()).chat([])
    assert client.seen == [[schema("submit")], [schema("submit")], tools, []]
    assert bound.tools == tools


@pytest.mark.asyncio
async def test_before_llm_restriction_preserves_terminal_tool_on_last_turn():
    class Observer:
        critical = True

        async def on_before_llm(self, ctx):
            return Intervention(allowed_tool_names=("submit",))

    client = SimpleNamespace()
    bound = bind_tools(client, [schema("search"), schema("submit")])
    llm, _, _ = await _prepare_llm_request(
        LoopConfig(), [Observer()], client, bound, [], {"_llm_strip_tools": True}, 1,
    )
    assert llm.tools == [schema("submit")]
