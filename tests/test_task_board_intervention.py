from __future__ import annotations

import asyncio
import json

from frontier_agent.components.observers.task_board import TaskBoardObserver
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import (
    LoopConfig,
    LoopPolicy,
    TurnContext,
    notify_observers,
)
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.tool import tool
from plugins.tools.task_board import (
    clear_board,
    drain_board_ops,
    restore_board_from_messages,
    snapshot_tasks,
)

_REMINDER = (
    "Current task board (keep it current via add_task / update_task; "
    "finish after resolving work or recording blocked work with notes and gap; "
    "blocked work permits only partial delivery):\nboard"
)


def _observer() -> TaskBoardObserver:
    return TaskBoardObserver(
        board_size=lambda _task_id: 1,
        render_board=lambda _task_id, _bus_task_id: "board",
        resolve_bus_task_id=lambda _scope: "bus-task",
    )


def _context(turn: int = 1) -> TurnContext:
    return TurnContext(
        turn=turn,
        max_turns=3,
        task_id="task",
        role_id="coordinator",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )


def test_dispatcher_collects_task_board_intervention() -> None:
    """Exercise the dispatcher contract, not the observer hook in isolation."""
    observer = _observer()

    interventions = asyncio.run(
        notify_observers([observer], "on_turn_end", _context()),
    )

    assert observer.critical is True
    assert len(interventions) == 1
    assert interventions[0].inject_messages == [_REMINDER]


def test_replayed_task_calls_restore_board_for_next_run() -> None:
    task_id = "continued-run"
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "add",
                "type": "function",
                "function": {
                    "name": "add_task",
                    "arguments": json.dumps({
                        "tasks": [
                            {"description": "核查主账户"},
                            {"description": "形成仓位结论"},
                        ]
                    }),
                },
            }],
        },
        {"role": "tool", "tool_call_id": "add", "content": "Added t1, t2"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "update",
                "type": "function",
                "function": {
                    "name": "update_task",
                    "arguments": json.dumps({
                        "updates": [{"id": "t1", "resolution": "resolved"}]
                    }),
                },
            }],
        },
        {"role": "tool", "tool_call_id": "update", "content": "Updated t1"},
    ]

    try:
        assert restore_board_from_messages(task_id, messages) == 2
        assert snapshot_tasks(task_id) == [
            {
                "id": "t1",
                "description": "核查主账户",
                "resolution": "resolved",
                "owners": [],
                "group": "",
            },
            {
                "id": "t2",
                "description": "形成仓位结论",
                "resolution": "open",
                "owners": [],
                "group": "",
            },
        ]
        # The resumed UI receives one full-board projection.
        assert drain_board_ops(task_id) == [{
            "op": "add",
            "ids": ["t1", "t2"],
            "phase": "execution",
        }]
    finally:
        clear_board(task_id)


@tool
async def _probe() -> str:
    """Keep the first loop turn productive so a second LLM turn runs."""
    return "ok"


class _ReminderCapturingLLM:
    model = "stub"

    def __init__(self) -> None:
        self.requests: list[list[dict]] = []

    async def chat(self, messages: list[dict], **_kwargs: object) -> LLMResponse:
        self.requests.append([dict(message) for message in messages])
        if len(self.requests) == 1:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "call-probe",
                    "type": "function",
                    "function": {
                        "name": "_probe",
                        "arguments": json.dumps({}),
                    },
                }],
                finish_reason="tool_calls",
            )
        return LLMResponse(content="done", finish_reason="stop")


def test_task_board_intervention_reaches_next_llm_request() -> None:
    """End to end: on_turn_end -> dispatcher -> history -> next LLM call."""
    llm = _ReminderCapturingLLM()

    result = asyncio.run(
        run_agent_loop(
            system_prompt="system",
            user_message="coordinate this task",
            llm=llm,
            tools=[_probe],
            config=LoopConfig(
                max_turns=3,
                task_id="task",
                role_id="coordinator",
                loop_policy=LoopPolicy(no_tool_behavior="stop"),
            ),
            observers=[_observer()],
        ),
    )

    assert len(llm.requests) == 2
    assert any(
        message.get("role") == "user" and message.get("content") == _REMINDER
        for message in llm.requests[1]
    ), "the task-board Intervention was swallowed before the next LLM call"
    assert result.stopped_by == "no_tool"
    assert result.final_content == "done"
