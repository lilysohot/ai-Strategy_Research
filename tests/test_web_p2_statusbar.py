"""P2.2 status bar (cli-web-parity §5.6): server-side event contract.

The status bar renders 阶段 · 耗时 · workflow · model · context · tools. The
run-level metadata (pipeline id, model, turn budget, context window) must ride
on the live ``run_started`` event — the trajectory replay already stamps
``model_name`` / ``tool_names`` / ``max_turns`` on its replayed copy
(``relay._traj_record_to_events``), but the live bridge emitted a bare event,
so a watching client showed an empty status bar until the replay caught up.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from server.bridge import BridgeObserver


async def test_loop_start_carries_run_meta():
    queue: asyncio.Queue = asyncio.Queue()
    obs = BridgeObserver(
        queue=queue,
        run_meta={"pipeline_id": "stateful-react-agent", "model_name": "gpt-x"},
    )
    await obs.on_loop_start(SimpleNamespace())
    event = queue.get_nowait()
    assert event["type"] == "run_started"
    assert event["pipeline_id"] == "stateful-react-agent"
    assert event["model_name"] == "gpt-x"


async def test_loop_start_carries_context_limit_from_config():
    queue: asyncio.Queue = asyncio.Queue()
    obs = BridgeObserver(queue=queue)
    # The loop's LoopConfig carries the context window (loop_types.LoopConfig).
    cfg = SimpleNamespace(context_token_limit=120_000)
    await obs.on_loop_start(cfg)
    event = queue.get_nowait()
    assert event["type"] == "run_started"
    assert event["context_limit"] == 120_000


async def test_loop_start_without_meta_omits_fields():
    queue: asyncio.Queue = asyncio.Queue()
    obs = BridgeObserver(queue=queue)
    await obs.on_loop_start(SimpleNamespace())
    event = queue.get_nowait()
    assert event["type"] == "run_started"
    assert "pipeline_id" not in event
    assert "model_name" not in event
