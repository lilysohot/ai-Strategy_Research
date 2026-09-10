from __future__ import annotations

from plugins.tools import ToolRegistry, get_builtin_tools

EXPECTED_TOOLS = {
    "add_task",
    "assign_task",
    "bash",
    "collect_reports",
    "corpus_fetch",
    "corpus_search",
    "create_file",
    "create_subagent",
    "data_coverage",
    "download_file",
    "file_editor_create",
    "file_editor_str_replace",
    "file_editor_view",
    "finish_planning",
    "glob_search",
    "grep_search",
    "market_financials",
    "market_history",
    "market_quote",
    "market_resolve",
    "position_sizing",
    "read_file",
    "recover_result",
    "run_python_code",
    "stop_subagent",
    "strategy_lint",
    "submit_report",
    "update_task",
    "view_image",
    "web_fetch",
    "web_search",
    "write_file",
}


def test_builtin_registry_is_an_explicit_allowlist() -> None:
    tools = get_builtin_tools()
    assert set(tools) == EXPECTED_TOOLS
    assert "finalize_answer" not in tools
    assert "tool_search" not in tools
    assert "dag_query" not in tools


def test_registry_round_trip() -> None:
    registry = ToolRegistry()
    registry.register_all(get_builtin_tools())

    assert registry.names() == sorted(EXPECTED_TOOLS)
    assert len(registry) == len(EXPECTED_TOOLS)
    assert registry.get("web_search") is get_builtin_tools()["web_search"]


# ── 投研内核（P0a）：TUI 下要真正可用，必须同时命中 4 处注册点 ──────────
# 漏掉 apodex 的 registry 会让 TUI 加载即 hard error（unknown tool name）；
# 漏掉 _READ_ONLY 会让每一次仓位计算都弹确认框。

FINANCE_TOOLS = ("position_sizing", "strategy_lint")


def test_finance_tools_are_in_the_terminal_registry() -> None:
    from apodex.agent_tools import terminal_tool_registry

    registry = terminal_tool_registry()
    for name in FINANCE_TOOLS:
        assert name in registry, f"{name} 不在 terminal_tool_registry()"


def test_finance_tools_are_auto_approved_as_read_only() -> None:
    from apodex.agent_tools import _READ_ONLY, assess_tool_risk

    for name in FINANCE_TOOLS:
        assert name in _READ_ONLY
        # safe == 不带 -y 也直接执行，不弹确认
        assert assess_tool_risk(name, {}, "/tmp").level == "safe"


def test_finance_tools_have_finance_metadata() -> None:
    from plugins.tools.meta import get_tool_meta

    for name in FINANCE_TOOLS:
        meta = get_tool_meta(name)
        assert meta.category == "finance"
        assert meta.timeout == 5
        assert meta.is_read_only is True
        assert meta.concurrency_safe is True
        # 输出都是小 JSON，截断只会把 computed_by 这类硬闸字段切掉
        assert meta.max_result_chars == 0


# ── 市场数据（同花顺 fuyao）：同样必须命中全部注册点 ──────────────────
# 漏掉 `_BUILTIN_TOOLS` ⇒ 工具不存在；漏掉 apodex registry ⇒ TUI 加载即 hard error；
# 漏掉 `_READ_ONLY` ⇒ 不带 -y 时每次取数都要人工点确认。

MARKET_TOOLS = (
    "market_resolve",
    "market_quote",
    "market_history",
    "market_financials",
)


def test_market_tools_are_in_the_terminal_registry() -> None:
    from apodex.agent_tools import terminal_tool_registry

    registry = terminal_tool_registry()
    for name in MARKET_TOOLS:
        assert name in registry, f"{name} 不在 terminal_tool_registry()"


def test_market_tools_are_auto_approved_as_read_only() -> None:
    """取数是只读网络读取，不该每次都弹确认框（否则 Agent 用不起来）。"""
    from apodex.agent_tools import _READ_ONLY, assess_tool_risk

    for name in MARKET_TOOLS:
        assert name in _READ_ONLY
        assert assess_tool_risk(name, {}, "/tmp").level == "safe"


def test_market_tools_have_network_aware_metadata() -> None:
    from plugins.tools.meta import get_tool_meta

    for name in MARKET_TOOLS:
        meta = get_tool_meta(name)
        assert meta.category == "finance"
        assert meta.is_read_only is True
        assert meta.concurrency_safe is True
        # 网络调用：timeout 必须 ≥15s（§5.7），否则退避重试没跑完就被掐断
        assert meta.timeout >= 15

    # market_quote 返回体带 quote_text / as_of，截断会让硬闸①的比对当场失效
    assert get_tool_meta("market_quote").max_result_chars == 0
