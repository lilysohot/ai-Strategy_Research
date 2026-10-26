from __future__ import annotations

import pytest

from frontier_agent.components.observers.stuck_target_guard import StuckTargetGuard
from frontier_agent.core.loop_types import ToolResult, TurnContext


def _ctx(turn: int) -> TurnContext:
    return TurnContext(
        turn=turn,
        max_turns=20,
        task_id="task",
        role_id="researcher",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )


def _failed_fetch() -> ToolResult:
    return ToolResult(
        name="web_fetch",
        args={"url": "https://example.test/report"},
        result="[ERROR]: upstream timed out",
        duration_ms=1,
        tool_call_id="fetch-1",
        is_error=True,
    )


@pytest.mark.asyncio
async def test_stuck_target_hint_publishes_actionable_alert() -> None:
    alerts: list[dict] = []
    guard = StuckTargetGuard(
        hint_after=2,
        escalate_after=3,
        on_alert=alerts.append,
    )

    for turn in (1, 2):
        ctx = _ctx(turn)
        await guard.on_tool_result(ctx, _failed_fetch())
        await guard.on_turn_end(ctx)

    assert alerts == [{
        "kind": "stuck_target",
        "host": "example.test",
        "failures": 2,
        "turn": 2,
        "action": "hint",
        "detail": "2 failed network turns targeted example.test; guard action=hint",
    }]
