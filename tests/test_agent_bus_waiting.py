from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus import (
    AgentBus,
    JobEntry,
    SubAgentRuntimeSpec,
    SubAgentSession,
    SubTask,
)
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, system_msg, tool_msg, user_msg
from frontier_agent.core.runtime.loop.message_trimmer import NullTrimmer
from frontier_agent.core.runtime.loop.tool_exec import execute_tools
from frontier_agent.core.runtime.registries import services as registry
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools.collect_reports import collect_reports
from workflows.agent_team.phase_budget import TeamPhaseBudget


def _session(task_id: str = "root") -> SubAgentSession:
    return SubAgentSession(
        session_id=f"{task_id}::worker",
        task_id=task_id,
        name="worker",
        role_id="researcher",
        system_prompt="test",
        tools=[],
        llm=None,
        trimmer=NullTrimmer(),
    )


@pytest.mark.asyncio
async def test_session_runtime_enforces_workflow_phase_timeout(monkeypatch) -> None:
    cancelled = False

    async def fake_run_agent_loop(**_kwargs):
        nonlocal cancelled
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        fake_run_agent_loop,
    )
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="worker",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
        runtime_spec=SubAgentRuntimeSpec(run_timeout_builder=lambda _item: 0.02),
    )
    await bus.submit_task_to_session(session_id, "do work")

    outcome = await bus.wait_any_session_detailed("root", timeout=1)

    assert outcome.result is not None
    _, result = outcome.result
    assert cancelled is True
    assert result.success is False
    assert result.error == "timeout"


@pytest.mark.asyncio
async def test_session_phase_timeout_salvages_last_completed_turn(monkeypatch) -> None:
    """A phase timeout must return work completed before the in-flight call."""
    finalizer_inputs: list[AgentLoopResult] = []

    async def fake_run_agent_loop(**kwargs):
        ctx = SimpleNamespace(
            turn=1,
            messages=[
                system_msg(kwargs["system_prompt"]),
                user_msg(kwargs["user_message"]),
                tool_msg("RETAINED_OBSERVATION", tool_call_id="read-1"),
            ],
            metadata={"content_acquisition": [{"status": "success"}]},
            tool_calls=[],
        )
        for observer in kwargs["observers"]:
            callback = getattr(observer, "on_turn_end", None)
            if callback is not None:
                await callback(ctx)
        await asyncio.Event().wait()

    async def force_finalizer(result, _item):
        finalizer_inputs.append(result)
        result.final_content = "RETAINED_OBSERVATION"
        return result

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        fake_run_agent_loop,
    )
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="worker",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
        runtime_spec=SubAgentRuntimeSpec(
            run_timeout_builder=lambda _item: 0.02,
            force_finalizer=force_finalizer,
        ),
    )
    await bus.submit_task_to_session(session_id, "do work")

    outcome = await bus.wait_any_session_detailed("root", timeout=1)

    assert outcome.result is not None
    _, result = outcome.result
    assert len(finalizer_inputs) == 1
    assert result.success is False
    assert result.error == "timeout"
    assert result.final_content == "RETAINED_OBSERVATION"
    assert result.metadata["content_acquisition"] == [{"status": "success"}]


@pytest.mark.asyncio
async def test_progress_alert_wakes_report_wait_without_finishing_member() -> None:
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,
        status="running",
    )

    async def alert() -> None:
        await asyncio.sleep(0.02)
        bus.publish_task_progress_alert(
            "root",
            agent="worker",
            kind="stuck_target",
            detail="five failed attempts against example.com",
        )

    alert_task = asyncio.create_task(alert())
    try:
        outcome = await bus.wait_any_session_detailed("root", timeout=5)
    finally:
        await alert_task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert outcome.reason == "progress_alert"
    assert outcome.result is None
    assert outcome.alert == {
        "agent": "worker",
        "kind": "stuck_target",
        "detail": "five failed attempts against example.com",
    }
    assert not task.done() or task.cancelled()


@pytest.mark.asyncio
async def test_job_progress_alert_is_routed_to_root_and_stale_alert_is_dropped() -> None:
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    bus._sessions[session.session_id] = session
    entry = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,
        status="running",
    )
    bus._jobs[job_id] = entry

    bus.publish_task_progress_alert(
        job_id,
        agent="worker",
        kind="stuck_target",
        detail="repeated failures",
    )
    outcome = await bus.wait_any_session_detailed("root", timeout=0)
    assert outcome.reason == "progress_alert"

    bus.publish_task_progress_alert(
        job_id,
        agent="worker",
        kind="stuck_target",
        detail="obsolete alert",
    )
    entry.status = "completed"
    session.current_job_id = None
    outcome = await bus.wait_any_session_detailed("root", timeout=0)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert outcome.reason == "no_pending"
    assert outcome.alert is None


@pytest.mark.asyncio
async def test_session_spawn_registers_job_before_eager_task_starts(
    monkeypatch,
) -> None:
    """The TUI's eager task factory must not outrun AgentBus bookkeeping."""
    async def fake_run_agent_loop(**kwargs):
        ctx = SimpleNamespace(
            turn=1,
            thinking="I should inspect the ClinVar source before generating data.",
            ai_text="I will query the source and validate the response.",
        )
        for observer in kwargs["observers"]:
            await observer.on_llm_delta(SimpleNamespace(
                turn=1, thinking_delta="I should inspect ", delta="",
            ))
            await observer.on_llm_delta(SimpleNamespace(
                turn=1, thinking_delta="the ClinVar source first.", delta="",
            ))
            await observer.on_llm_response(ctx)
            await observer.on_tool_call(ctx, {
                "name": "web_search", "args": {"query": "ClinVar API"},
            })
            await observer.on_tool_result(ctx, SimpleNamespace(
                name="web_search", result="found source", is_error=False,
            ))
        return AgentLoopResult(
            messages=[
                system_msg(kwargs["system_prompt"]),
                user_msg(kwargs["user_message"]),
                assistant_msg("finished"),
            ],
            final_content="finished",
            stopped_by="final_answer",
        )

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        fake_run_agent_loop,
    )
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(asyncio.eager_task_factory)
    try:
        bus = AgentBus()
        session_id = await bus.create_session(
            task_id="root",
            name="worker",
            role_id="researcher",
            system_prompt="test",
            tools_override=[],
            llm_override=object(),
        )
        job_id = await bus.submit_task_to_session(session_id, "do work")
        outcome = await bus.wait_any_session_detailed("root", timeout=0)
    finally:
        loop.set_task_factory(previous_factory)

    assert outcome.reason == "ready"
    assert outcome.result is not None
    _, result = outcome.result
    assert result.success
    assert result.final_content == "finished"
    assert bus._jobs[job_id].status == "completed"
    assert bus._sessions[session_id].current_job_id is None
    snapshot = bus.describe_sessions_for_task("root")[0]
    assert [event["kind"] for event in snapshot["events"]] == [
        "thinking", "message", "tool_call", "tool_result",
    ]
    assert snapshot["events"][0]["detail"].startswith("I should inspect")
    assert len([e for e in snapshot["events"] if e["kind"] == "thinking"]) == 1


@pytest.mark.asyncio
async def test_wait_reconciles_cancelled_task_instead_of_fake_timeout() -> None:
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,
        status="running",
    )

    outcome = await bus.wait_any_session_detailed("root", timeout=1800)

    assert outcome.reason == "ready"
    assert outcome.elapsed_s < 1
    assert outcome.result is not None
    _, result = outcome.result
    assert not result.success
    assert result.error_class == "CancelledError"
    assert session.current_job_id is None
    assert bus._jobs[job_id].status == "aborted"


@pytest.mark.asyncio
async def test_wait_reports_actual_timeout_only_for_live_task() -> None:
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,
        status="running",
    )

    try:
        outcome = await bus.wait_any_session_detailed("root", timeout=0.02)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert outcome.reason == "timeout"
    assert outcome.result is None
    assert 0.01 <= outcome.elapsed_s < 1
    assert session.current_job_id == job_id


@pytest.mark.asyncio
async def test_wait_reports_unpublished_when_a_task_ends_empty_handed() -> None:
    """A task that finished during the wait is not "nothing to wait for".

    Real time elapsed, so telling the coordinator to discount the wait (what
    ``no_pending`` means) would be the same wrong-elapsed-time steering in the
    opposite direction.
    """
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"

    async def _finish_without_publishing() -> None:
        await asyncio.sleep(0.02)
        # Mimic a wrapper that completes but leaves the session's bookkeeping
        # untouched, so reconciliation has nothing to hand back either.
        bus._jobs[job_id].status = "completed"
        session.current_job_id = None

    task = asyncio.create_task(_finish_without_publishing())
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,  # type: ignore[arg-type]
        status="running",
    )

    outcome = await bus.wait_any_session_detailed("root", timeout=5)

    assert outcome.reason == "unpublished"
    assert outcome.result is None
    assert outcome.elapsed_s >= 0.02


@pytest.mark.asyncio
async def test_session_snapshot_freezes_a_finished_worker_duration() -> None:
    """The UI reads ``elapsed_s`` verbatim, so it must stop growing.

    ``active`` is what tells a renderer whether the number is still counting;
    without it a finished worker's row ticks up for as long as the fan-in
    blocks.
    """
    async def fake_run_agent_loop(**kwargs):
        return AgentLoopResult(
            messages=[
                system_msg(kwargs["system_prompt"]),
                user_msg(kwargs["user_message"]),
                assistant_msg("done"),
            ],
            final_content="done",
            stopped_by="final_answer",
        )

    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="market_research",
        role_id="agent_team_sub",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )

    unassigned = bus.describe_sessions_for_task("root")[0]
    assert unassigned["status"] == "unassigned"
    assert unassigned["active"] is False
    assert unassigned["elapsed_s"] == 0.0
    assert unassigned["role_id"] == "agent_team_sub"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "frontier_agent.components.agent_bus.bus.run_agent_loop",
            fake_run_agent_loop,
        )
        await bus.submit_task_to_session(session_id, "do work")
        assert await bus.wait_any_session("root", timeout=5) is not None

    finished = bus.describe_sessions_for_task("root")[0]
    assert finished["status"] == "idle"
    assert finished["active"] is False
    frozen = finished["elapsed_s"]

    await asyncio.sleep(0.05)
    assert bus.describe_sessions_for_task("root")[0]["elapsed_s"] == frozen


@pytest.mark.asyncio
async def test_wait_distinguishes_no_pending_work_from_timeout() -> None:
    bus = AgentBus()
    session = _session()
    bus._sessions[session.session_id] = session

    outcome = await bus.wait_any_session_detailed("root", timeout=1800)

    assert outcome.reason == "no_pending"
    assert outcome.result is None
    assert outcome.elapsed_s < 1


@pytest.mark.asyncio
async def test_collect_reports_describes_actual_wait_not_requested_ceiling() -> None:
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,
        status="running",
    )
    services_before = registry.snapshot()
    registry.register(AgentBus, bus)
    progress: list[tuple[list[dict], bool]] = []

    class ProgressObserver:
        def on_subagent_status(self, snapshots, *, done=False, timeout_s=0):
            progress.append((snapshots, done))

    token = set_current_execution_scope(ExecutionScope(
        task_id="root",
        metadata={"sdk_extra_observers": [ProgressObserver()]},
    ))

    try:
        text = await collect_reports.ainvoke({"timeout": 0.11})
    finally:
        reset_current_execution_scope(token)
        registry.restore(services_before)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    assert "actual 0.1s wait" in text
    assert "requested maximum 0.11s" in text
    assert "Timed out after" not in text
    assert progress
    assert progress[0][0][0]["name"] == "worker"
    assert progress[0][0][0]["status"] == "running"
    assert progress[0][0][0]["role_id"] == "researcher"
    assert progress[0][0][0]["active"] is True
    # The teardown publish must have landed *before* the tool returned, or a
    # follow-up collect_reports can have its fresh progress card torn down by
    # the previous call's late callback.
    assert progress[-1][1] is True


@pytest.mark.asyncio
async def test_collect_reports_does_not_wait_past_research_phase() -> None:
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,
        status="running",
    )
    now = asyncio.get_running_loop().time()
    phase_budget = TeamPhaseBudget(
        started_monotonic_s=now - 20,
        research_dispatch_deadline_s=now - 10,
        research_deadline_s=now - 1,
        publication_deadline_s=now + 30,
        finalization_deadline_s=now + 60,
        state={},
    )
    services_before = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(ExecutionScope(
        task_id="root",
        metadata={SWARM_SCOPE_KEY: SimpleNamespace(phase_budget=phase_budget)},
    ))
    started = asyncio.get_running_loop().time()
    try:
        text = await collect_reports.ainvoke({"timeout": 1800})
    finally:
        reset_current_execution_scope(token)
        registry.restore(services_before)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert asyncio.get_running_loop().time() - started < 0.2
    assert "research collection window is closed" in text


@pytest.mark.asyncio
async def test_intervention_cancels_collect_reports_wait_immediately() -> None:
    """A parked coordinator must yield to user input, not the 30m timeout."""
    from apodex.steer import SteerInbox

    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    worker_task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=worker_task,  # type: ignore[arg-type]
        status="running",
    )

    class Renderer:
        def queued(self, text: str) -> None:
            pass

    inbox = SteerInbox(Renderer())
    services_before = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(ExecutionScope(task_id="root"))
    try:
        collecting = asyncio.create_task(execute_tools(
            [{"name": "collect_reports", "args": {"timeout": 60}}],
            {"collect_reports": collect_reports},
            timeout=65,
            turn=1,
            count_offset=0,
            interrupt_waiter=lambda _call: inbox.wait_for_input(),
        ))
        await asyncio.sleep(0.02)
        assert not collecting.done()

        inbox.enqueue("change the plan")

        results = await asyncio.wait_for(collecting, timeout=1)
    finally:
        reset_current_execution_scope(token)
        registry.restore(services_before)
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task

    assert len(results) == 1
    assert results[0].interrupted is True
    assert "new user message arrived" in results[0].result
    assert inbox.drain() == ["change the plan"]


@pytest.mark.asyncio
async def test_progress_heartbeat_survives_a_failing_observer() -> None:
    """Progress rendering is decoration around the caller's real work.

    A renderer that raises must not kill the heartbeat (freezing the UI for
    the rest of the wait) nor leave an unretrieved task exception behind.
    """
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = job_id
    session.total_task_count = 1
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="work", role_id="researcher"),
        task=task,  # type: ignore[arg-type]
        status="running",
    )
    services_before = registry.snapshot()
    registry.register(AgentBus, bus)
    calls: list[bool] = []

    class ExplodingObserver:
        def on_subagent_status(self, snapshots, *, done=False, timeout_s=0):
            calls.append(done)
            raise RuntimeError("renderer is wedged")

    token = set_current_execution_scope(ExecutionScope(
        task_id="root",
        metadata={"sdk_extra_observers": [ExplodingObserver()]},
    ))

    try:
        text = await collect_reports.ainvoke({"timeout": 0.11})
    finally:
        reset_current_execution_scope(token)
        registry.restore(services_before)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert "actual 0.1s wait" in text
    assert calls and calls[-1] is True


@pytest.mark.asyncio
async def test_current_job_metadata_exposes_what_a_stop_would_interrupt() -> None:
    """``stop_subagent`` needs to know whether the running job is the publish
    task: stopping that one discards the run's deliverable, because
    ``StopSignalObserver`` stops by popping the turn holding the write.

    A copy is returned, so a caller inspecting a live job cannot mutate the
    dispatched task's own metadata.
    """
    bus = AgentBus()
    session = _session()
    job_id = "root::worker::1"
    metadata = {"can_publish": True, "output_paths": ["/outputs/answer.md"]}
    session.current_job_id = job_id
    bus._sessions[session.session_id] = session
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="root",
        item=SubTask(question="publish", role_id="researcher", metadata=metadata),
        status="running",
    )

    read = bus.current_job_metadata(session.session_id)
    assert read == metadata
    read["can_publish"] = False
    assert bus._jobs[job_id].item.metadata["can_publish"] is True

    # Unknown session, and a session sitting idle between tasks.
    assert bus.current_job_metadata("root::nobody") == {}
    session.current_job_id = None
    assert bus.current_job_metadata(session.session_id) == {}


@pytest.mark.asyncio
async def test_immediate_dispatch_preserves_current_job_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The free dispatch path must retain metadata just like the queued path."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_agent_loop(**kwargs):
        started.set()
        await release.wait()
        return AgentLoopResult(
            messages=[
                system_msg(kwargs["system_prompt"]),
                user_msg(kwargs["user_message"]),
                assistant_msg("published"),
            ],
            final_content="published",
            stopped_by="final_answer",
        )

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        fake_run_agent_loop,
    )
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="publisher",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    metadata = {"can_publish": True, "output_paths": ["/outputs/answer.md"]}

    await bus.submit_task_to_session(
        session_id, "publish", task_metadata=metadata,
    )
    await started.wait()
    try:
        assert bus.current_job_metadata(session_id) == metadata
    finally:
        release.set()
        await bus.wait_any_session_detailed("root", timeout=1)
