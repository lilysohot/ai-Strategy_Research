"""Web stop must close the shared team gate, including queued members."""

import asyncio

import pytest

from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver


async def test_stop_rejects_queued_members_without_reopening_approval() -> None:
    gate = ApprovalGate()
    events = []
    first_prompt = asyncio.Event()

    def emit(event):
        events.append(event)
        if event["type"] == "approval_requested":
            first_prompt.set()

    observer = ApprovalObserver(gate, emit, "/tmp", timeout=5)
    call = {"name": "unknown_tool", "args": {}}
    tasks = [
        asyncio.create_task(observer.for_subagent(str(i)).on_tool_call(None, call))
        for i in range(2)
    ]
    try:
        await asyncio.wait_for(first_prompt.wait(), 1)
        # Exercise the worker's stdin-thread entry point, not only loop-local stop.
        await asyncio.to_thread(gate.reject_pending)
        results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert all(result and result.skip_with_result for result in results)
        assert sum(event["type"] == "approval_requested" for event in events) == 1
        assert not gate._pending
        later = await observer.on_tool_call(None, {"name": "read_file", "args": {"path": "x"}})
        assert later and later.skip_with_result
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_closed_gate_refuses_late_approval_and_future_requests() -> None:
    gate = ApprovalGate()
    aid = gate.open()
    gate.reject_pending()
    assert not gate.resolve(aid, ApprovalDecision(decision="once"))
    assert (await gate.wait(aid)).source == "stopped"
    later = gate.open()
    assert (await asyncio.wait_for(gate.wait(later), 1)).source == "stopped"


@pytest.mark.parametrize("already_allowed", [False, True])
async def test_stop_wins_over_prior_session_allow(already_allowed) -> None:
    gate = ApprovalGate()
    call = {"name": "unknown_tool", "args": {}}
    if already_allowed:
        gate.remember(call["name"], call["args"], "session_all")
    gate.reject_pending()
    events = []
    result = await ApprovalObserver(gate, events.append, "/tmp").on_tool_call(None, call)
    assert result and result.skip_with_result
    assert events == []


async def test_stop_wakes_parked_fanin() -> None:
    gate = ApprovalGate()
    observer = ApprovalObserver(gate, lambda event: None, "/tmp")
    waiting = asyncio.create_task(observer.wait_for_tool_interrupt(None, {}))
    gate.reject_pending()
    assert await asyncio.wait_for(waiting, 1)


@pytest.mark.parametrize("reason", ["paused", "cancelled", "failed", "completed"])
async def test_team_member_cleanup_on_coordinator_exit(reason) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from frontier_agent.core.loop_types import AgentLoopResult
    from workflows.agent_team.lifecycle import run_with_member_cleanup

    bus = SimpleNamespace(cleanup_task=AsyncMock())

    async def execute():
        if reason == "cancelled":
            raise asyncio.CancelledError()
        if reason == "failed":
            raise RuntimeError("coordinator failed")
        return AgentLoopResult(messages=[], stopped_by=reason)

    if reason in ["cancelled", "failed"]:
        with pytest.raises(asyncio.CancelledError if reason == "cancelled" else RuntimeError):
            await run_with_member_cleanup(execute(), bus=bus, task_id="team")
    else:
        await run_with_member_cleanup(execute(), bus=bus, task_id="team")
    assert bus.cleanup_task.await_count == (0 if reason == "completed" else 1)


def test_web_team_mounts_use_artifact_api_paths(tmp_path) -> None:
    from workflows.agent_team.nodes.main_agent import (
        _resolve_sandbox_binds,
        _resolve_worktree_root,
    )

    workspace = tmp_path / "ws"
    outputs = workspace / "outputs"
    inputs = tmp_path / "inputs"
    state = {
        "metadata": {
            "_trial_dir": str(tmp_path / "run"),
            "_sandbox_workspace_root": str(workspace),
            "_sandbox_outputs_dir": str(outputs),
            "_sandbox_mounts": [{"src": str(inputs), "dst": "/inputs", "mode": "ro"}],
        }
    }
    assert _resolve_worktree_root(state, "task") == workspace
    main, members, resolved_outputs = _resolve_sandbox_binds(state, workspace)
    assert resolved_outputs == outputs
    for binds in [main, members]:
        assert (str(inputs), "/inputs", True) in binds
        assert (str(outputs), "/outputs", False) in binds


async def test_web_team_bwrap_reads_uploads_and_writes_outputs(tmp_path, monkeypatch) -> None:
    import os

    from plugins.tools._sandbox import (
        BwrapSandbox,
        bwrap_available,
        clear_task_sandbox,
        set_task_sandbox,
    )
    from plugins.tools.create_file import create_file
    from plugins.tools.glob_search import glob_search
    from plugins.tools.read_file import read_file
    from server.worker import apply_env

    if not bwrap_available():
        pytest.skip("requires working bubblewrap")
    paths = {name: tmp_path / name for name in ["workspace", "outputs", "inputs", "spill", "run"]}
    for path in paths.values():
        path.mkdir()
    (paths["inputs"] / "sample.txt").write_text("TEAM_UPLOAD_42")
    monkeypatch.setattr(os, "environ", os.environ.copy())
    apply_env(
        paths,
        backend="bwrap",
        wall_time_s=600,
        max_turns=10,
        model="test",
        base_url="https://example.invalid",
        api_key="test",
        canonical_mounts=True,
    )
    sandbox = BwrapSandbox(
        workspace=paths["workspace"],
        binds=(
            (str(paths["inputs"]), "/inputs", True),
            (str(paths["outputs"]), "/outputs", False),
        ),
    )
    token = set_task_sandbox(sandbox)
    try:
        assert "TEAM_UPLOAD_42" in await read_file.func(path="/inputs/sample.txt")
        assert "sample.txt" in await glob_search.func(pattern="*.txt", path="/inputs")
        result = await create_file.func(
            path="/outputs/report.txt", ops=[{"create": {"content": "TEAM_RESULT"}}]
        )
        assert (paths["outputs"] / "report.txt").read_text() == "TEAM_RESULT", result
    finally:
        clear_task_sandbox(token)
        sandbox.kill()


async def test_cancel_bwrap_command_reaps_process_without_cancelling_sibling(tmp_path) -> None:
    import os

    from plugins.tools._sandbox import BwrapSandbox, arun_sandbox_cmd, bwrap_available

    if not bwrap_available():
        pytest.skip("requires working bubblewrap")
    sandbox = BwrapSandbox(workspace=tmp_path)
    commands = [
        asyncio.create_task(
            arun_sandbox_cmd(
                sandbox,
                f"echo $$ > /workspace/{name}.pid; exec sleep 120",
                timeout=130,
            )
        )
        for name in ["first", "sibling"]
    ]
    try:
        async with asyncio.timeout(5):
            while not all((tmp_path / f"{name}.pid").exists() for name in ["first", "sibling"]):
                await asyncio.sleep(0.01)
        first, sibling = [
            int((tmp_path / f"{name}.pid").read_text()) for name in ["first", "sibling"]
        ]
        commands[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(commands[0], 2)
        with pytest.raises(ProcessLookupError):
            os.kill(first, 0)
        os.kill(sibling, 0)
        commands[1].cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(commands[1], 2)
        with pytest.raises(ProcessLookupError):
            os.kill(sibling, 0)
    finally:
        for command in commands:
            command.cancel()
        await asyncio.gather(*commands, return_exceptions=True)
        sandbox.kill()
