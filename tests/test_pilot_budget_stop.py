"""A pilot budget stop is a decision, not a provider failure.

Field evidence: three aborted runs all ended as ``stopped / llm_error``, so a cap
that fired by construction read as "the model failed" — and each stop burned five
physical attempts plus backoff retrying a request the budget had already refused.

These tests drive the real ``run_agent_loop`` with only the model boundary mocked,
so the assertion is about the loop's classification, not about the guard's stubs.
"""

from __future__ import annotations

import pytest

from frontier_agent.core.loop_types import LoopConfig
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.infra.pilot_budget import PilotBudgetExhausted


def _config() -> LoopConfig:
    return LoopConfig(max_turns=1, max_llm_retries=5, llm_timeout=600)


class _RefusingLLM:
    """Stands in for the transport: every request is refused by the budget."""

    model = "offline-pilot"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    async def chat(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise PilotBudgetExhausted(self.reason)


async def _run(monkeypatch: pytest.MonkeyPatch, reason: str) -> tuple[object, _RefusingLLM]:
    llm = _RefusingLLM(reason)
    # No sleep: a retry would show up as extra calls rather than as elapsed time.
    result = await run_agent_loop(
        system_prompt="pilot",
        user_message="go",
        llm=llm,  # type: ignore[arg-type]
        tools=[],
        observers=[],
        config=_config(),
    )
    return result, llm


async def test_cap_stop_is_not_retried_and_is_not_llm_error(monkeypatch) -> None:
    result, llm = await _run(monkeypatch, "completion_tokens")
    assert llm.calls == 1, "a budget refusal is final; it must not be retried"
    assert result.stopped_by == "budget_exhausted"
    assert result.stopped_by != "llm_error"
    assert result.metadata.get("llm_error") in (None, "")
    assert result.metadata.get("pilot_budget_stop") == "completion_tokens"


async def test_unknown_usage_stop_reports_its_own_reason(monkeypatch) -> None:
    result, llm = await _run(monkeypatch, "usage_unavailable")
    assert llm.calls == 1
    assert result.stopped_by == "usage_unavailable"
    assert result.metadata.get("pilot_budget_stop") == "usage_unavailable"
