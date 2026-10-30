"""Fail-closed tool boundary check for monitoring-driven workers."""

from typing import Any

from frontier_agent.core.loop_types import BaseObserver, ToolCallIntervention, TurnContext
from plugins.tools.watch_targets import request


class WatchPauseObserver(BaseObserver):
    async def on_tool_call(
        self, ctx: TurnContext, tool_call: dict[str, Any]
    ) -> ToolCallIntervention | None:
        result = await request("guard")
        if not result.get("ok"):
            return ToolCallIntervention(
                skip_with_result=str(result.get("error")), skip_is_error=True
            )
        return None
