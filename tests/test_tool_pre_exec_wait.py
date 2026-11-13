"""Tool execution time and the wait before it must be attributable separately.

A run reported tools that "hung for minutes" while every tool body finished in
tens of milliseconds. The gap was pre-execution wait (approval hook, coalescing,
scheduler slot), which was invisible. ``queued_ms`` makes it explicit.
"""

import asyncio
import time

from frontier_agent.core.runtime.loop.tool_exec import execute_tools
from frontier_agent.core.tool import tool


@tool
async def slow_tool(value: str) -> str:
    """Return the value after a short hop.

    Args:
        value: Echoed back.
    """
    await asyncio.sleep(0)
    return value


async def test_pre_execution_wait_is_reported_apart_from_execution_time():
    accepted = time.monotonic()
    await asyncio.sleep(0.05)  # stand-in for the approval/coalescing window
    results = await execute_tools(
        [{"name": "slow_tool", "args": {"value": "x"}, "id": "c1"}],
        {"slow_tool": slow_tool},
        timeout=5,
        turn=1,
        count_offset=0,
        accepted_monotonic=accepted,
    )
    assert results[0].is_error is False
    assert results[0].queued_ms >= 40
    assert results[0].duration_ms < 40


async def test_without_a_stamp_no_wait_is_claimed():
    results = await execute_tools(
        [{"name": "slow_tool", "args": {"value": "x"}, "id": "c1"}],
        {"slow_tool": slow_tool},
        timeout=5,
        turn=1,
        count_offset=0,
    )
    assert results[0].queued_ms == 0
