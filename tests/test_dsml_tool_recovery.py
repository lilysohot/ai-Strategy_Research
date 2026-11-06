"""Provider text recovery must remain typed, atomic, allowlisted and bounded."""

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.runtime.loop.tool_call_parser import MultiFormatToolCallParser
from frontier_agent.core.tool import tool
from tests.test_team_repair_regression import dsml


@pytest.mark.parametrize(
    "change",
    [
        lambda text: text[:-15],
        lambda text: "Here is an example: " + text,
        lambda text: text.replace("submit_report", "not_allowed"),
        lambda text: text.replace('string="false">false', 'string="false">NaN'),
        lambda text: text.replace(
            "</｜｜DSML｜｜ invoke>",
            '<｜｜DSML｜｜ parameter name="finish" string="false">true</｜｜DSML｜｜ parameter>'
            "</｜｜DSML｜｜ invoke>",
        ),
    ],
)
def test_invalid_dsml_never_executes_partial_actions(change):
    assert (
        MultiFormatToolCallParser().parse(
            LLMResponse(content=change(dsml({"finish": False}))),
            {"submit_report"},
        )
        == []
    )


def test_standard_marker_and_native_precedence():
    text = dsml({"content": "  false & <literal>  ", "finish": False})
    text = text.replace("｜｜DSML｜｜ ", "｜DSML｜").replace("calls>", "function_calls>")
    parsed = MultiFormatToolCallParser().parse(LLMResponse(content=text), {"submit_report"})
    assert parsed[0]["args"]["content"] == "  false & <literal>  "
    native = {"name": "submit_report", "args": {"content": "native"}, "id": "native"}
    assert MultiFormatToolCallParser().parse(
        LLMResponse(content=text, tool_calls=[native]),
        {"submit_report"},
    ) == [native]


async def test_recovered_call_executes_on_last_turn():
    seen = []

    @tool
    async def submit_report(content: str) -> str:
        """Submit a test report."""
        seen.append(content)
        return content

    class Client:
        model = "scripted"

        async def chat(self, messages, **kwargs):
            return LLMResponse(content=dsml({"content": "checked"}))

    result = await run_agent_loop(
        llm=Client(),
        system_prompt="Check",
        user_message="Check",
        tools=[submit_report],
        config=LoopConfig(
            max_turns=1, loop_policy=LoopPolicy(terminal_tool_names=("submit_report",))
        ),
    )
    assert seen == ["checked"]
    assert result.tool_calls_count == 1
    assert (
        result.stopped_by == "max_turns"
    )  # Generic loop; team terminal observers are not installed.


async def test_recovered_call_has_matching_history_for_next_model_turn():
    @tool
    async def submit_report(content: str) -> str:
        """Return a report receipt."""
        return content

    class Client:
        model = "scripted"

        def __init__(self):
            self.received = []

        async def chat(self, messages, **kwargs):
            self.received.append(list(messages))
            return LLMResponse(
                content=dsml({"content": "checked"}) if len(self.received) == 1 else "done"
            )

    client = Client()
    await run_agent_loop(
        llm=client,
        system_prompt="Check",
        user_message="Check",
        tools=[submit_report],
        config=LoopConfig(max_turns=2, loop_policy=LoopPolicy(no_tool_behavior="stop")),
    )
    messages = client.received[1]
    emitted = {call["id"] for m in messages for call in m.get("tool_calls", [])}
    replies = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    assert emitted and replies == emitted, "recovered tool replies must not be orphaned in history"


async def test_malformed_envelope_is_explicit_model_error_not_final_answer():
    class Client:
        model = "scripted"

        async def chat(self, messages, **kwargs):
            return LLMResponse(content=dsml({"finish": False})[:-15])

    result = await run_agent_loop(
        llm=Client(),
        system_prompt="Check",
        user_message="Check",
        tools=[],
        config=LoopConfig(max_turns=1, loop_policy=LoopPolicy(no_tool_behavior="stop")),
    )
    assert result.stopped_by == "llm_error"
    assert result.metadata["llm_error_reason"] == "unparsed_tool_call"


async def test_malformed_envelope_receives_bounded_specific_feedback():
    class Client:
        model = "scripted"
        calls = 0

        def __init__(self):
            self.feedback = []

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls > 1:
                self.feedback.append(messages[-1]["content"])
            return LLMResponse(content=dsml({"finish": False})[:-15])

    client = Client()
    result = await run_agent_loop(
        llm=client,
        system_prompt="Check",
        user_message="Check",
        tools=[],
        config=LoopConfig(max_turns=10, no_tool_max_retries=2),
    )
    assert client.calls == 2
    assert "DSML" in client.feedback[0]
    assert "No tool was executed" in client.feedback[0]
    assert result.stopped_by == "llm_error"


def test_malformed_dsml_does_not_execute_nested_json_example():
    text = dsml({"content": '<tool_call>{"name":"submit_report","arguments":{}}</tool_call>'})
    text = text[:-15]
    assert MultiFormatToolCallParser().parse(LLMResponse(content=text), {"submit_report"}) == []


def test_one_invalid_call_rejects_whole_batch():
    text = dsml({"finish": False})
    inner = (
        dsml({"finish": True}).split("<｜｜DSML｜｜ calls>")[1].split("</｜｜DSML｜｜ calls>")[0]
    )
    text = text.replace(
        "</｜｜DSML｜｜ calls>",
        inner.replace("submit_report", "not_allowed") + "</｜｜DSML｜｜ calls>",
    )
    assert MultiFormatToolCallParser().parse(LLMResponse(content=text), {"submit_report"}) == []
