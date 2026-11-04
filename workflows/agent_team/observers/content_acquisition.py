"""Retain acquisition limits independently of a member's prose report."""

from __future__ import annotations

import json
from typing import Any

from frontier_agent.core.loop_types import AgentLoopResult, BaseObserver, ToolResult, TurnContext
from plugins.tools._corpus_handoff import evidence_identity, observed_corpus_evidence
from plugins.tools._verification import record_corpus_observation


class ContentAcquisitionObserver(BaseObserver):
    """Track observed access to a source; do not infer semantic claim support."""

    def __init__(self) -> None:
        self._sources: dict[tuple[str, str], dict[str, Any]] = {}
        self._corpus_evidence: dict[str, dict[str, Any]] = {}

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> None:
        if result.name not in {"web_fetch", "view_image", "read_file", "corpus_search", "corpus_fetch"}:
            return
        try:
            payload = json.loads(result.result)
        except (ValueError, TypeError):
            payload = None
        if result.name in {"corpus_search", "corpus_fetch"}:
            if isinstance(payload, dict) and not result.is_error:
                for record in observed_corpus_evidence(result.name, payload):
                    self._corpus_evidence[evidence_identity(record)] = record
            # Also checkpoint here: cancellation may prevent on_loop_end.
            ctx.metadata["corpus_evidence"] = list(self._corpus_evidence.values())
            if result.name == "corpus_fetch":
                return
        if result.name == "corpus_search":
            data = payload if isinstance(payload, dict) else {}
            coverage = data.get("coverage")
            observation = {
                "tool": result.name, "source": str(result.args.get("query") or ""),
                "obtained": not result.is_error and data.get("ok") is True,
                "status": "success" if not result.is_error and data.get("ok") is True else "failed",
                "coverage": coverage if isinstance(coverage, dict) else {
                    "processing": "unknown", "availability": "unknown",
                },
            }
            self._sources[(result.name, observation["source"])] = observation
            record_corpus_observation(observation)
            ctx.metadata["content_acquisition"] = list(self._sources.values())
            return
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
        result.metadata["corpus_evidence"] = list(self._corpus_evidence.values())
