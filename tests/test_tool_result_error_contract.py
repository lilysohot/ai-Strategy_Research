"""Shared tool-result error classification across kernel and Web projection."""

from __future__ import annotations

from frontier_agent.core.runtime.loop.tool_exec import (
    execute_tools,
    tool_result_text_is_error,
)
from frontier_agent.core.tool import tool


def test_tool_result_text_error_contract_is_prefix_scoped() -> None:
    assert tool_result_text_is_error("Error: upstream unavailable")
    assert tool_result_text_is_error("[error] invalid workbook operation")
    assert tool_result_text_is_error("[read_file error] exit=1: missing")
    assert tool_result_text_is_error("[office_writer error] conversion failed")
    assert tool_result_text_is_error("[Exit code 127]\ncommand not found")

    assert not tool_result_text_is_error("ok")
    assert not tool_result_text_is_error("Processed rows. Error rate: 0%.")
    assert not tool_result_text_is_error("[Exit code 0]\ncompleted")
    assert not tool_result_text_is_error("[blocked by safety policy: denied]")


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
