"""A completed report must not become a new tool request (Web Run 289539f8)."""

import pytest

from frontier_agent.components.observers.leaked_tool_call_retry import LeakedToolCallRetryObserver
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy, TurnContext
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.tool import tool

TOOLS = ("investment_position_sizing", "request_investment_input", "web_search")


def context(text, metadata=None, tool_calls=None):
    return TurnContext(
        turn=1,
        max_turns=10,
        task_id="test",
        role_id="react",
        ai_text=text,
        thinking="",
        tool_calls=tool_calls or [],
        messages=[],
        usage=None,
        metadata=metadata if metadata is not None else {},
    )


@pytest.mark.parametrize(
    "text",
    [
        "估值 PE(TTM) 19.86。\n`investment_position_sizing` 被拒；仓位计算未完成。",
        "`investment_position_sizing` 已执行，结果 ok=false。\n估值 PE(TTM) 19.86。",
        '我此前已调用 `request_investment_input(use_case="plan_analysis")` 登记补数意图。',
        '`request_investment_input(use_case="plan_analysis")` 已执行，结果为已记录。',
        'I already called web_search(query="example"); no results were found.',
        "I will summarize the findings. `web_search` returned no results.",
        'Do not call web_search(query="example"); the source is unavailable.',
        "The parameter was rejected by `investment_position_sizing`.",
        'After calling web_search(query="example"), I found no relevant results.',
    ],
)
async def test_report_prose_is_not_a_tool_request(text):
    assert await LeakedToolCallRetryObserver(TOOLS).on_llm_response(context(text)) is None


@pytest.mark.parametrize(
    "text",
    [
        'web_search(query="example")',
        '```python\nweb_search(query="example")\n```',
        'web_search {"query": "example"}',
        "Let me call web_search with this query.",
        'I will web_search(query="example")',
        "I will use web_search next.",
        "Next, I will use web_search.",
        "下一步调用 `web_search` 查询资料。",
        '<tool_call>{"name":"web_search","arguments":{}}</tool_call>',
    ],
)
async def test_real_unstructured_invocation_still_gets_retried(text):
    intervention = await LeakedToolCallRetryObserver(TOOLS).on_llm_response(context(text))
    assert intervention is not None
    assert intervention.continue_to_next_turn


async def test_structured_calls_reset_temperature_but_not_the_total_retry_cap():
    observer = LeakedToolCallRetryObserver(TOOLS, max_nudges_per_task=2)
    metadata = {}
    for _ in range(2):
        assert await observer.on_llm_response(context("Let me call web_search.", metadata))
        assert metadata["_llm_temp_override"] == 0.3
        assert (
            await observer.on_llm_response(context("", metadata, [{"name": "web_search"}])) is None
        )
    assert await observer.on_llm_response(context("Let me call web_search.", metadata)) is None


async def test_completed_report_exits_real_loop_without_reexecuting_failed_tool():
    calls = []

    @tool
    async def investment_position_sizing() -> str:
        """Return the existing missing-data result."""
        calls.append(True)
        return '{"ok":false,"error":"missing frozen fields"}'

    report = "估值 PE(TTM) 19.86；`investment_position_sizing` 被拒，仓位计算未完成。"

    class ScriptedLLM:
        model = "test"
        count = 0

        async def chat(self, messages, **kwargs):
            self.count += 1
            if self.count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        {
                            "id": "sizing",
                            "type": "function",
                            "function": {"name": "investment_position_sizing", "arguments": "{}"},
                        }
                    ],
                )
            return LLMResponse(content=report)

    llm = ScriptedLLM()
    result = await run_agent_loop(
        system_prompt="Report limitations honestly.",
        user_message="Continue.",
        llm=llm,
        tools=[investment_position_sizing],
        config=LoopConfig(max_turns=5, loop_policy=LoopPolicy(no_tool_behavior="stop")),
        observers=[LeakedToolCallRetryObserver(TOOLS)],
    )
    assert llm.count == 2, "A finished answer was incorrectly forced into another model call"
    assert len(calls) == 1
    assert result.final_content == report
    assert result.stopped_by == "no_tool"
