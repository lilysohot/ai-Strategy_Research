"""A reasoning-only interruption must not publish a prior tool preamble as final."""

from __future__ import annotations

import pytest

from frontier_agent.core.errors import LLMReasoningRunaway
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from server.run_outcome import interruption_reason
from workflows.stateful_react_agent.observers import FinalAnswerSalvageObserver

_PROGRESS = "我已收集到充分的语料证据。现在提交结论证据清单（A4），然后完成最终研究结论。"


class _RunawayLLM:
    model = "stub"

    def __init__(self, kind: str, recover: bool = False) -> None:
        self.kind = kind
        self.recover = recover
        self.calls = 0

    async def chat(self, messages: list[dict], **kwargs: object) -> LLMResponse:
        self.calls += 1
        if self.recover and self.calls > 1:
            return LLMResponse(content="完整结论", finish_reason="stop")
        if self.kind == "early":
            raise LLMReasoningRunaway(
                elapsed_s=120,
                estimated_tokens=4482,
                trigger="time",
                partial_response=LLMResponse(content="", reasoning_content="unfinished reasoning"),
            )
        return LLMResponse(content="", finish_reason="length", usage={"completion_tokens": 2048})


def _history() -> list[dict]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "研究光模块业务"},
        {
            "role": "assistant",
            "content": _PROGRESS,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "corpus_submit_manifest",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"unsupported":4}'},
    ]


def _salvage(llm: _RunawayLLM) -> FinalAnswerSalvageObserver:
    return FinalAnswerSalvageObserver(
        llm=llm,
        timeout=1,
        task_description="研究光模块业务",
        thinking_format="tag",
        salvage_infra_errors=True,
        language="zh",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["early", "capped"])
@pytest.mark.parametrize("behavior", ["stop", "nudge"])
async def test_exhausted_runaway_is_not_a_completed_research_answer(
    kind: str, behavior: str
) -> None:
    llm = _RunawayLLM(kind)
    result = await run_agent_loop(
        system_prompt="system",
        user_message="继续研究",
        initial_messages=_history(),
        llm=llm,
        tools=[],
        observers=[_salvage(llm)],
        config=LoopConfig(
            max_turns=2,
            max_llm_retries=1,
            no_tool_max_retries=1,
            loop_policy=LoopPolicy(no_tool_behavior=behavior),
        ),
    )
    assert result.stopped_by == "llm_error"
    assert result.metadata["llm_error_reason"] == (
        "reasoning_runaway_early" if kind == "early" else "reasoning_runaway"
    )
    assert interruption_reason(result.stopped_by) == "llm_error"
    assert result.metadata["final_answer_source"] == "deterministic_fallback"
    assert result.final_content and _PROGRESS not in result.final_content
    assert llm.calls == 1, "failure reporting must not launch another research/rescue call"


@pytest.mark.asyncio
async def test_nudge_policy_can_still_recover_on_the_next_turn() -> None:
    llm = _RunawayLLM("early", recover=True)
    result = await run_agent_loop(
        system_prompt="system",
        user_message="继续研究",
        initial_messages=_history(),
        llm=llm,
        tools=[],
        observers=[_salvage(llm)],
        config=LoopConfig(
            max_turns=3,
            max_llm_retries=1,
            no_tool_max_retries=2,
            loop_policy=LoopPolicy(no_tool_behavior="nudge"),
        ),
    )
    assert result.stopped_by == "no_tool"
    assert result.final_content == "完整结论"
    assert "llm_error" not in result.metadata
    assert llm.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["early", "capped"])
async def test_successful_resample_is_still_a_normal_completion(kind: str, monkeypatch) -> None:
    from frontier_agent.core.runtime.loop import _call

    monkeypatch.setattr(_call, "_RUNAWAY_BACKOFF_S", 0)
    llm = _RunawayLLM(kind, recover=True)
    result = await run_agent_loop(
        system_prompt="system",
        user_message="继续研究",
        initial_messages=_history(),
        llm=llm,
        tools=[],
        observers=[_salvage(llm)],
        config=LoopConfig(
            max_turns=2,
            max_llm_retries=2,
            loop_policy=LoopPolicy(no_tool_behavior="stop"),
        ),
    )
    assert result.stopped_by == "no_tool"
    assert result.final_content == "完整结论"
    assert "llm_error" not in result.metadata
    assert llm.calls == 2
