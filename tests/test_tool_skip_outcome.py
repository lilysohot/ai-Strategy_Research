"""Skipped failures must travel with the first winning intervention."""

import pytest

from frontier_agent.core.loop_types import ToolCallIntervention, TurnContext, notify_tool_call


@pytest.mark.parametrize("first_error", [False, True])
async def test_first_skip_owns_its_error_flag(first_error):
    class Observer:
        def __init__(self, result):
            self.result = result

        async def on_tool_call(self, ctx, tool_call):
            return self.result

    ctx = TurnContext(1, 2, "task", "role", "", "", [], [], None, {})
    result = await notify_tool_call(
        [
            Observer(ToolCallIntervention(skip_is_error=True, metadata_updates={"noticed": True})),
            Observer(ToolCallIntervention(skip_with_result="first", skip_is_error=first_error)),
            Observer(ToolCallIntervention(skip_with_result="second", skip_is_error=not first_error)),
        ],
        ctx,
        {"name": "read_file", "args": {"path": "/inputs/a"}},
    )
    assert result.skip_with_result == "first"
    assert result.skip_is_error is first_error
    assert result.metadata_updates == {"noticed": True}


def test_legacy_cached_skip_keeps_success_default():
    assert not ToolCallIntervention(skip_with_result="cached content").skip_is_error
