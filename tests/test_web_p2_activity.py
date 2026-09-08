"""P2.1 Activity timeline: skipped-tool semantics on the SSE event producers.

The terminal renders a tool call whose result is *synthetic* (never ran —
per-turn tool-call cap, user rejection, safety block) as ``skipped``, not as a
clean success (apodex/observers.py ``_SYNTHETIC_RESULT_MARKERS``). The web
bridge (live) and the relay replay must carry the same signal, otherwise the
Activity timeline marks calls that never ran as ``done``.

Run with::
    uv run pytest tests/test_web_p2_activity.py -q
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from server.bridge import BridgeObserver
from server.relay import _traj_record_to_events


def _result(text: str, *, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        result=text,
        name="bash",
        is_error=is_error,
        duration_ms=12,
        tool_call_id="call_1",
    )


# — bridge (live path) ————————————————————————————————
async def test_bridge_marks_synthetic_tool_result_skipped():
    queue: asyncio.Queue = asyncio.Queue()
    obs = BridgeObserver(queue=queue)

    await obs.on_tool_result(SimpleNamespace(turn=2), _result(
        "[tool call skipped] exceeded the per-turn tool-call cap of 5; "
        "re-issue it in a later turn if still needed.",
    ))

    event = queue.get_nowait()
    assert event["type"] == "tool_finished"
    # A call that never ran is skipped, not a clean success.
    assert event["skipped"] is True
    assert event["ok"] is True


async def test_bridge_normal_result_is_not_skipped():
    queue: asyncio.Queue = asyncio.Queue()
    obs = BridgeObserver(queue=queue)

    await obs.on_tool_result(SimpleNamespace(turn=1), _result("ls -la\nfile.txt"))

    event = queue.get_nowait()
    assert event["type"] == "tool_finished"
    assert not event.get("skipped")
    assert event["ok"] is True


async def test_bridge_error_result_is_not_skipped():
    queue: asyncio.Queue = asyncio.Queue()
    obs = BridgeObserver(queue=queue)

    await obs.on_tool_result(SimpleNamespace(turn=1), _result(
        "Error: file not found", is_error=True,
    ))

    event = queue.get_nowait()
    assert event["ok"] is False
    assert not event.get("skipped")


# — relay (replay path) ———————————————————————————————
def test_replay_marks_synthetic_result_skipped():
    events = _traj_record_to_events({
        "t": "result",
        "turn": 3,
        "tool_call_id": "call_9",
        "name": "create_file",
        "result": "[user rejected this call] approval denied",
        "error": False,
        "ms": 0,
    })

    finished = [e for e in events if e["type"] == "tool_finished"]
    assert len(finished) == 1
    assert finished[0]["skipped"] is True
    assert finished[0]["ok"] is True


def test_replay_normal_result_is_not_skipped():
    events = _traj_record_to_events({
        "t": "result",
        "turn": 3,
        "tool_call_id": "call_9",
        "name": "create_file",
        "result": "written",
        "error": False,
        "ms": 5,
    })

    finished = [e for e in events if e["type"] == "tool_finished"]
    assert len(finished) == 1
    assert not finished[0].get("skipped")
