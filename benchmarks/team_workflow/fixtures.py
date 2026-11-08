"""Fixed web data, preserving production tool schemas and blocking fallthrough."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from frontier_agent.core.tool import Tool, ToolOutcome
from plugins.tools import get_builtin_tools
from plugins.tools._content_outcome import content_limitation, fetch_in_order

COORDINATION = (
    "create_subagent",
    "assign_task",
    "collect_reports",
    "stop_subagent",
    "add_task",
    "update_task",
    "finish_planning",
    "submit_report",
)


def fixed_tools(sources: list[dict[str, Any]]) -> dict[str, Tool]:
    """All queries return this small corpus; URL fetch is exact and fail-closed.

    This tests cooperation/evidence use, not search ranking. No shell, database,
    file reader, downloader or real web tool is registered in the worker.
    """
    builtins = get_builtin_tools()
    pages = {source["url"]: source for source in sources}

    async def search(**kwargs: Any) -> str:
        return json.dumps(
            {
                "ok": True,
                "status": "success",
                "query": kwargs.get("query"),
                "results": [
                    {
                        "url": p["url"],
                        "title": p["title"],
                        "snippet": "Fixed evaluation source. Fetch this URL for the original text.",
                    }
                    for p in sources
                ],
            },
            ensure_ascii=False,
        )

    async def fetch(**kwargs: Any) -> str | ToolOutcome:
        urls = kwargs.get("url") or []
        if isinstance(urls, str):
            urls = [urls]
        if kwargs.get("fallback_urls"):
            if len(urls) != 1:
                raise ValueError("fallback_urls requires exactly one primary URL")

            async def fetch_one(url: str) -> str | ToolOutcome:
                page = pages.get(url)
                if page and page.get("status", "success") == "success":
                    return page["content"]
                return content_limitation(url, "Frozen source unavailable; no network fallback.")

            return await fetch_in_order(urls[0], kwargs["fallback_urls"], fetch_one)
        items = []
        for url in urls:
            page = pages.get(url)
            ok = bool(page and page.get("status", "success") == "success")
            items.append(
                {
                    "source": url,
                    "ok": ok,
                    "status": "success" if ok else "unavailable",
                    "content": page["content"] if ok and page else "",
                    "detail": "" if ok else "Frozen source unavailable; no network fallback.",
                }
            )
        return json.dumps(
            {
                "ok": bool(items) and all(i["ok"] for i in items),
                "status": "success" if items and all(i["ok"] for i in items) else "partial",
                "acquired_count": sum(i["ok"] for i in items),
                "failed_count": sum(not i["ok"] for i in items),
                "items": items,
            },
            ensure_ascii=False,
        )

    result = {name: builtins[name] for name in COORDINATION}
    result["web_search"] = replace(builtins["web_search"], func=search)
    result["web_fetch"] = replace(builtins["web_fetch"], func=fetch)
    return result
