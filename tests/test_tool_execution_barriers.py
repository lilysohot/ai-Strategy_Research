"""Tool barriers preserve parallel reads, ordering, and fail-closed observers."""

import asyncio

import pytest

from frontier_agent.core.loop_types import (
    BaseObserver,
    LoopConfig,
    ToolCallIntervention,
    TurnContext,
)
from frontier_agent.core.runtime.loop.agent_loop import _execute_tool_calls
from frontier_agent.core.tool import tool


@pytest.mark.parametrize("outcome", ["ok", "failed", "denied"])
async def test_barrier_waits_for_preceding_calls_and_result_observers(outcome):
    completed = []
    arrived = 0
    both_started = asyncio.Event()
    mutation_notified = False

    @tool
    async def parallel_read(name: str) -> str:
        """Both reads must start before either completes."""
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        completed.append(name)
        return name

    @tool
    async def mutation() -> str:
        """Change state after the reads."""
        assert set(completed) == {"left", "right"}
        if outcome == "failed":
            raise ValueError("mutation failed")
        completed.append("mutation")
        return "ok"

    mutation.metadata["execution_barrier"] = True

    @tool
    async def dependent() -> str:
        """Only run after successful notification of the mutation."""
        assert mutation_notified
        completed.append("dependent")
        return "ok"

    class Guard(BaseObserver):
        critical = True

        async def on_tool_call(self, ctx, call):
            if call["name"] == "mutation" and outcome == "denied":
                return ToolCallIntervention(skip_with_result="denied", skip_is_error=True)
            if call["name"] == "dependent" and not mutation_notified:
                return ToolCallIntervention(skip_with_result="not updated", skip_is_error=True)
            return None

        async def on_tool_result(self, ctx, result):
            nonlocal mutation_notified
            if result.name == "mutation" and not result.is_error:
                mutation_notified = True

    calls = [
        {"id": "left", "name": "parallel_read", "args": {"name": "left"}},
        {"id": "right", "name": "parallel_read", "args": {"name": "right"}},
        {"id": "mutation", "name": "mutation", "args": {}},
        {"id": "dependent", "name": "dependent", "args": {}},
    ]
    messages = []
    ctx = TurnContext(1, 2, "barrier", "test", "", "", calls, messages, None, {})
    reason, count = await _execute_tool_calls(
        LoopConfig(),
        [Guard()],
        {t.name: t for t in (parallel_read, mutation, dependent)},
        messages,
        {},
        1,
        0,
        ctx,
        calls,
    )
    assert (reason, count) == ("", 4)
    assert ("dependent" in completed) is (outcome == "ok")
    assert [
        m.tool_call_id if hasattr(m, "tool_call_id") else m["tool_call_id"] for m in messages
    ] == [c["id"] for c in calls]
