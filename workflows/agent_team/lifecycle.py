"""Close member jobs before a stopped coordinator leaves its execution phase."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.loop_types import AgentLoopResult

logger = logging.getLogger(__name__)


async def run_with_member_cleanup(
    execution: Awaitable[AgentLoopResult],
    *,
    bus: AgentBus,
    task_id: str,
) -> AgentLoopResult:
    """Retain normal fan-in; cancel members on pause, failure or cancellation."""
    completed = False
    try:
        result = await execution
        completed = result.stopped_by != "paused"
        return result
    finally:
        if not completed:
            try:
                await asyncio.wait_for(bus.cleanup_task(task_id), timeout=15)
            except Exception:
                logger.exception("Team stop cleanup failed (task=%s)", task_id)
