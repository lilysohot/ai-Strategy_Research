"""Shared tool-result error classification across kernel and Web projection."""

from __future__ import annotations

from frontier_agent.core.runtime.loop.tool_exec import (
    execute_tools,
    tool_result_text_is_error,
)
from frontier_agent.core.tool import ToolOutcome, tool


def test_tool_result_text_error_contract_is_prefix_scoped() -> None:
    assert tool_result_text_is_error("Error: upstream unavailable")
    assert tool_result_text_is_error("[error] invalid workbook operation")
    assert tool_result_text_is_error("[read_file error] exit=1: missing")
    assert tool_result_text_is_error("[office_writer error] conversion failed")
    assert tool_result_text_is_error("[Exit code 127]\ncommand not found")
    assert tool_result_text_is_error('{"status": "error", "error": "timeout"}')
    assert tool_result_text_is_error('{"ok": false, "error": "missing input"}')
    assert tool_result_text_is_error('{"success": false, "error": "upstream failed"}')

    assert not tool_result_text_is_error("ok")
    assert not tool_result_text_is_error("Processed rows. Error rate: 0%.")
    assert not tool_result_text_is_error("[Exit code 0]\ncompleted")
    assert not tool_result_text_is_error("[blocked by safety policy: denied]")
    assert not tool_result_text_is_error("[no error] completed")
    assert not tool_result_text_is_error('{"status": "downloaded", "error": ""}')


async def test_execute_tools_sets_is_error_for_legacy_string_failure() -> None:
    @tool(name="legacy_reader")
    async def legacy_reader() -> str:
        """Return a legacy reader failure string."""
        return "[read_file error] exit=1: FileNotFoundError"

    result = (await execute_tools(
        [{"name": "legacy_reader", "args": {}, "id": "call_1"}],
        {"legacy_reader": legacy_reader},
        timeout=5,
        turn=1,
        count_offset=0,
    ))[0]

    assert result.is_error is True


async def test_execute_tools_preserves_structured_failure_before_stringification() -> None:
    @tool(name="structured_reader")
    async def structured_reader() -> dict[str, object]:
        """Return a structured failure from a modern tool."""
        return {"ok": False, "error": "missing input"}

    result = (await execute_tools(
        [{"name": "structured_reader", "args": {}, "id": "call_2"}],
        {"structured_reader": structured_reader},
        timeout=5,
        turn=1,
        count_offset=0,
    ))[0]

    assert result.is_error is True


async def test_execute_tools_accepts_an_explicit_tool_outcome() -> None:
    @tool(name="explicit_outcome")
    async def explicit_outcome() -> ToolOutcome:
        """Return an explicitly classified result."""
        return ToolOutcome("provider rejected the request", is_error=True)

    result = (await execute_tools(
        [{"name": "explicit_outcome", "args": {}, "id": "call_3"}],
        {"explicit_outcome": explicit_outcome},
        timeout=5,
        turn=1,
        count_offset=0,
    ))[0]

    assert result.result == "provider rejected the request"
    assert result.is_error is True


async def test_agent_team_download_file_json_failure_is_an_error() -> None:
    from plugins.tools.download_file import download_file

    result = (await execute_tools(
        [{"name": "download_file", "args": {"url": ""}, "id": "call_4"}],
        {"download_file": download_file},
        timeout=5,
        turn=1,
        count_offset=0,
    ))[0]

    assert '"status": "error"' in result.result
    assert result.is_error is True
