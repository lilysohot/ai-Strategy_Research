"""Reuse complete immutable fetch results still visible in the active conversation.

This is not a search cache: corpus publications can change between searches.
No results survive context eviction, and no summaries acquire evidence status.
"""

from __future__ import annotations

import json
import re
from typing import Any

from frontier_agent.core.loop_types import BaseObserver, ToolCallIntervention, TurnContext


def _fetch_key(args: dict[str, Any]) -> str:
    normalized = {"locator": None, "locators": None, "cursor": None,
                  "view": "full", "max_chars": 6000, **args}
    normalized.pop("force_refresh", None)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


class CorpusContextReuseObserver(BaseObserver):
    """Short-circuit only identical, successful, complete version-pinned fetches."""

    async def on_tool_call(
        self, ctx: TurnContext, tool_call: dict,
    ) -> ToolCallIntervention | None:
        args = tool_call.get("args")
        if (tool_call.get("name") != "corpus_fetch" or not isinstance(args, dict)
                or args.get("force_refresh")):
            return None
        doc_id = args.get("doc_id", "")
        if not isinstance(doc_id, str) or not re.fullmatch(r"cv2:[0-9a-f]{64}", doc_id):
            return None
        key = _fetch_key(args)
        matches: set[str] = set()
        for message in ctx.messages or []:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    if fn.get("name") != "corpus_fetch":
                        continue
                    try:
                        old_args = json.loads(fn.get("arguments") or "{}")
                        if isinstance(old_args, dict) and _fetch_key(old_args) == key:
                            matches.add(call["id"])
                    except (ValueError, TypeError, KeyError):
                        continue
            elif message.get("role") == "tool" and message.get("tool_call_id") in matches:
                try:
                    body = json.loads(message.get("content") or "")
                except (ValueError, TypeError):
                    continue
                if not isinstance(body, dict) or body.get("ok") is not True:
                    continue
                if body.get("doc_id") != doc_id or body.get("build_id") != doc_id[4:]:
                    continue
                if (body.get("next_cursor") or body.get("item_errors") or body.get("unresolved")
                        or body.get("fetch_complete") is False):
                    continue
                items = body.get("items")
                if items is None:
                    items = [body]
                if not isinstance(items, list) or not items or not all(
                    isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]
                    for item in items
                ):
                    continue
                return ToolCallIntervention(skip_with_result=json.dumps({
                    "ok": True, "reused_from_context": True, "doc_id": doc_id,
                    "source_tool_call_id": message["tool_call_id"],
                    "evidence_refs": [item["evidence_ref"] for item in items if item.get("evidence_ref")],
                    "hint": "同版本、同参数的完整原文仍在当前上下文，直接引用；无需重复读取。需要重新读取时设置 force_refresh=true。",
                }, ensure_ascii=False))
        return None
