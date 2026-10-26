"""Retain acquisition limits independently of a member's prose report."""

from __future__ import annotations

import json
from typing import Any

from frontier_agent.core.loop_types import AgentLoopResult, BaseObserver, ToolResult, TurnContext


class ContentAcquisitionObserver(BaseObserver):
    """Track observed access to a source; do not infer semantic claim support."""

    def __init__(self) -> None:
        self._sources: dict[tuple[str, str], dict[str, Any]] = {}

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> None:
        if result.name not in {"web_fetch", "view_image", "read_file"}:
            return
        try:
            payload = json.loads(result.result)
        except (ValueError, TypeError):
            payload = None
        records = []
        if isinstance(payload, dict) and payload.get("ok") is False:
            records = payload.get("items") or [payload]
        if not records:
            if result.name == "web_fetch":
                raw = result.args.get("url")
            elif result.name == "view_image":
                raw = result.args.get("image_path_or_url")
            else:
                raw = result.args.get("path")
            targets = raw if isinstance(raw, list) else [raw]
            records = [
                {"source": target, "status": "failed" if result.is_error else "success"}
                for target in targets if isinstance(target, str) and target
            ]
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("source"), str):
                continue
            source = record["source"]
            key = (result.name, source)
            status = str(record.get("status") or "unavailable")
            previous = self._sources.get(key, {})
            obtained = previous.get("obtained", False) or status == "success"
            observation = {
                "tool": result.name, "source": source, "obtained": obtained,
                "status": "success" if obtained else status,
                "last_attempt_status": status,
            }
            for field in ("detail", "coverage"):
                value = record.get(field)
                if value not in (None, "", [], {}):
                    observation[field] = value
                elif field in previous:
                    observation[field] = previous[field]
            self._sources[key] = observation
        ctx.metadata["content_acquisition"] = list(self._sources.values())

    async def on_loop_end(self, result: AgentLoopResult) -> None:
        result.metadata["content_acquisition"] = list(self._sources.values())
