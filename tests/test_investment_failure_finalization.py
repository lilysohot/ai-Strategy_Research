from __future__ import annotations

from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import AgentLoopResult
from workflows.stateful_react_agent import _runtime
from workflows.stateful_react_agent.observers import ReportSynthesisObserver


@pytest.mark.parametrize(
    "stopped_by", ["llm_error", "wall_deadline", "budget_exhausted", "max_attempts"]
)
@pytest.mark.asyncio
async def test_abnormal_stop_uses_deterministic_partial_instead_of_guessing(
    monkeypatch, stopped_by: str
) -> None:
    calls = 0

    async def unsafe_rescue(*args, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(content="可以买，300股合理。", reasoning_content="")

    monkeypatch.setattr(_runtime, "chat_with_fallback_budget", unsafe_rescue)
    result = AgentLoopResult(messages=[], stopped_by=stopped_by)

    await _runtime.force_final_answer(
        result,
        SimpleNamespace(),
        5,
        task_description="准备购买工业富联300股，你觉得合适吗",
        language="Simplified Chinese",
    )

    assert calls == 0
    assert "不对尚未验证的结果做断言" in result.metadata["final_answer"]
    assert result.metadata["final_answer_source"] == "deterministic_fallback"


@pytest.mark.parametrize(
    "stopped_by", ["llm_error", "wall_deadline", "budget_exhausted", "max_attempts"]
)
@pytest.mark.asyncio
async def test_reporter_does_not_turn_abnormal_stop_into_an_investment_conclusion(
    stopped_by: str,
) -> None:
    class UnsafeReporter:
        calls = 0

        async def stream(self, *args, **kwargs):
            self.calls += 1
            yield SimpleNamespace(
                content="可以买，300股合理。",
                reasoning_content="",
                usage={},
                model="fake",
                provider="fake",
            )

    llm = UnsafeReporter()
    result = AgentLoopResult(messages=[], stopped_by=stopped_by)
    observer = ReportSynthesisObserver(
        llm=llm,
        timeout=5,
        task_description="准备购买工业富联300股，你觉得合适吗",
        language="Simplified Chinese",
    )

    await observer.on_loop_end(result)

    assert llm.calls == 0
    assert "不对尚未验证的结果做断言" in result.metadata["final_answer"]
    assert result.metadata["final_answer_source"] == "deterministic_fallback"
