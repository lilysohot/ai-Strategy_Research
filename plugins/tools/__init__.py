"""Explicit built-in tool registry for the OSS workflows."""

from __future__ import annotations

import logging

from frontier_agent.core.tool import Tool
from plugins.tools.assign_task import assign_task
from plugins.tools.bash import bash
from plugins.tools.collect_reports import collect_reports
from plugins.tools.corpus_fetch import corpus_fetch
from plugins.tools.corpus_search import corpus_search
from plugins.tools.create_file import create_file
from plugins.tools.create_subagent import create_subagent
from plugins.tools.data_coverage import data_coverage
from plugins.tools.download_file import download_file
from plugins.tools.file_editor import (
    file_editor_create,
    file_editor_str_replace,
    file_editor_view,
)
from plugins.tools.glob_search import glob_search
from plugins.tools.grep_search import grep_search
from plugins.tools.market_financials import market_financials
from plugins.tools.market_history import market_history
from plugins.tools.market_quote import market_quote
from plugins.tools.market_resolve import market_resolve
from plugins.tools.position_sizing import position_sizing
from plugins.tools.read_file import read_file
from plugins.tools.recover_result import recover_result
from plugins.tools.run_python_code import run_python_code
from plugins.tools.stop_subagent import stop_subagent
from plugins.tools.strategy_lint import strategy_lint
from plugins.tools.submit_report import submit_report
from plugins.tools.task_board import add_task, finish_planning, update_task
from plugins.tools.view_image import view_image
from plugins.tools.web_fetch import web_fetch
from plugins.tools.web_search import web_search
from plugins.tools.write_file import write_file

logger = logging.getLogger(__name__)

_BUILTIN_TOOLS: list[Tool] = [
    web_search,
    web_fetch,
    download_file,
    bash,
    create_subagent,
    assign_task,
    add_task,
    update_task,
    finish_planning,
    collect_reports,
    stop_subagent,
    read_file,
    create_file,
    write_file,
    # 投研内核（P0a）。两者都是纯函数：确定性计算 + 确定性校验，
    # 无网络、无文件、无共享状态。加入本 allowlist 只让它们「可解析」，
    # 是否对某个 Agent 可见另由各 profile 的 tools 列表决定。
    position_sizing,
    strategy_lint,
    # 语料检索 / 取证（P0b）。只读本地 SQLite，无网络、无写入。
    # 加入本 allowlist 只让它们「可解析」，是否可见另由各 profile 决定。
    corpus_search,
    corpus_fetch,
    # 数据源覆盖度探测（开局一次，串起 corpus 与 market，只读）。
    data_coverage,
    # 市场数据（同花顺 fuyao）。只读、无写入、按按需拉取（本模块不落库）。
    # 未配置 THS_API_KEY 或 MARKET_ENABLED=false 时工具返回 ok=false，不影响其他工具。
    market_resolve,
    market_quote,
    market_history,
    market_financials,
    file_editor_view,
    file_editor_create,
    file_editor_str_replace,
    submit_report,
    view_image,
    grep_search,
    glob_search,
    run_python_code,
    recover_result,
]


def get_builtin_tools() -> dict[str, Tool]:
    """Return the allowlisted built-ins as a name-to-tool mapping."""
    return {tool.name: tool for tool in _BUILTIN_TOOLS}


class ToolRegistry:
    """Central registration and fail-closed role filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_all(self, tools: dict[str, Tool]) -> None:
        self._tools.update(tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_all(self) -> dict[str, Tool]:
        return dict(self._tools)

    def get_for_role(self, role_id: str) -> list[Tool]:
        try:
            from frontier_agent.core.runtime.registries import services
            from frontier_agent.core.runtime.registries.agents import AgentRegistry

            allowed = set(services.get(AgentRegistry).get_tools_for(role_id))
            return [tool for name, tool in self._tools.items() if name in allowed]
        except Exception as exc:
            logger.warning("Tool lookup for role %s failed: %s", role_id, exc)
            return []

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


__all__ = [
    "ToolRegistry",
    "get_builtin_tools",
]
