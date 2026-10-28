from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus.models import SubTask
from frontier_agent.components.finalization import resolve_research_wall
from frontier_agent.components.observers.wall_clock_guard import WallClockGuard
from frontier_agent.core.errors import LLMStreamStalled
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import (
    WALL_DEADLINE_MONOTONIC_KEY,
    AgentLoopResult,
    LoopConfig,
)
from frontier_agent.core.messages import tool_msg
from frontier_agent.core.runtime.loop._streaming import _stream_llm_response
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.runtime.loop.tool_exec import max_tool_wall_time_s
from frontier_agent.core.tool import tool
from server.orchestrator import _pipeline_wall_timeout_s
from server.profile import PROFILE_NAME, build_profile_overrides
from workflows.agent_team.nodes.main_agent import (
    _bounded_wind_down_wait_s,
    _build_team_phase_budget,
    _resolve_team_loop_timeouts,
)
from workflows.agent_team.phase_budget import TeamPhaseBudget, TeamPhaseBudgetObserver
from workflows.agent_team.profile import load_swarm_profile
from workflows.agent_team.subagent_runtime import (
    InheritedWallClockDeadlineObserver,
    SwarmSubagentRuntime,
    build_swarm_session_runtime_spec,
)


def _web_team_agent_config() -> dict:
    overrides = build_profile_overrides(pipeline_id="agent_team")
    return load_swarm_profile(PROFILE_NAME, overrides=overrides)["agent"]


def test_web_first_chunk_budget_is_resolved_for_the_coordinator() -> None:
    timeouts = _resolve_team_loop_timeouts(_web_team_agent_config())

    assert timeouts.first_chunk_timeout_s == 45
    assert timeouts.logical_call_timeout_s == 180
    assert timeouts.loop_config_kwargs()["first_chunk_timeout"] == 45


def test_web_team_reserves_a_real_publication_window(monkeypatch) -> None:
    """The 2026-10-25 live runs exhausted the old 450s research window after
    both reports, leaving the publisher either unassigned or with no useful
    first turn. Team mode has its own modestly extended hard wall, while single
    mode keeps its established budget.
    """
    monkeypatch.setenv("FRONTIER_AGENT_TASK_WALL_TIME_S", "1050")
    team = _web_team_agent_config()
    timeouts = _resolve_team_loop_timeouts(team)
    finalization_s = float(team["finalization_timeout_s"])
    wind_down_s = float(team.get("team_wind_down_timeout_s", 15))
    reserve_s = max(
        float(team.get("wall_deadline_reserve_s", 180)),
        max_tool_wall_time_s(timeouts.tool_timeout_s)
        + finalization_s
        + wind_down_s,
    )

    wall = resolve_research_wall(
        team,
        reserve_s=reserve_s,
        label_prefix="agent_team test",
    )

    assert team["research_wall_time_s"] == 720
    assert timeouts.tool_timeout_s == 135
    assert finalization_s == 120
    assert team["wall_deadline_reserve_s"] == 300
    assert team["publication_phase_timeout_s"] == 180
    assert wall.research_deadline_s == 720
    assert wall.hard_total_s == 1050


def test_team_phase_budget_closes_research_before_publication() -> None:
    state = {}
    budget = TeamPhaseBudget(
        started_monotonic_s=100,
        research_dispatch_deadline_s=500,
        research_deadline_s=700,
        publication_deadline_s=880,
        finalization_deadline_s=1000,
        state=state,
    )

    assert budget.sync_phase(499) == "research"
    assert budget.can_dispatch_research(499) is True
    assert budget.sync_phase(500) == "draining"
    assert budget.can_dispatch_research(500) is False
    assert budget.sync_phase(700) == "consolidating"
    assert budget.can_dispatch_publication(700) is True
    assert budget.sync_phase(880) == "finalizing"
    assert budget.can_dispatch_publication(880) is False


def test_consolidating_report_wait_preserves_verification_budget() -> None:
    now = time.monotonic()
    budget = TeamPhaseBudget(
        started_monotonic_s=now - 720,
        research_dispatch_deadline_s=now - 165,
        research_deadline_s=now - 1,
        publication_deadline_s=now + 179,
        finalization_deadline_s=now + 300,
        state={},
    )
    phase, deadline = budget.wait_deadline(publication_pending=True)
    assert phase == "consolidating"
    assert deadline == budget.publication_deadline_s


@pytest.mark.asyncio
async def test_research_member_enters_handoff_before_hard_deadline() -> None:
    now = time.monotonic()
    budget = TeamPhaseBudget(
        started_monotonic_s=now - 560,
        research_dispatch_deadline_s=now - 5,
        research_deadline_s=now + 160,
        publication_deadline_s=now + 340,
        finalization_deadline_s=now + 460,
        state={},
    )
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(phase_budget=budget), session_name="worker", task_id="root",
    )
    observers = spec.observers_builder("root.job.1", SubTask("research"), 1)
    inherited = next(o for o in observers if isinstance(o, InheritedWallClockDeadlineObserver))
    ctx = SimpleNamespace(metadata={})
    decision = await inherited.on_tool_call(
        ctx, {"name": "web_fetch", "args": {"url": "https://example.test/new"}},
    )
    assert decision is not None, "late exploration must yield to a real report window"
    assert "submit_report" in decision.skip_with_result
    for name in ("submit_report", "publish_handoff"):
        assert await inherited.on_tool_call(ctx, {"name": name, "args": {}}) is None
    hint = await inherited.on_turn_end(ctx)
    assert hint is not None and hint.stop_reason is None
    assert "submit_report" in hint.inject_messages[0]

    # A verifier/publisher is doing the reserved work, so research handoff
    # must not block its evidence reads or file writes.
    for metadata in (
        {"uses_publication_budget": True}, {"can_publish": True},
        {"verification_checks": [{"check_id": "c1"}]},
    ):
        observers = spec.observers_builder("root.job.2", SubTask("reserved", metadata=metadata), 1)
        observer = next(o for o in observers if isinstance(o, InheritedWallClockDeadlineObserver))
        assert await observer.on_tool_call(ctx, {"name": "read_file", "args": {}}) is None

    early_verifier = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(phase_budget=budget), session_name="final_verifier", task_id="root",
    )
    observers = early_verifier.observers_builder("root.job.3", SubTask("verify"), 1)
    observer = next(o for o in observers if isinstance(o, InheritedWallClockDeadlineObserver))
    assert await observer.on_tool_call(ctx, {"name": "web_fetch", "args": {}}) is None


@pytest.mark.asyncio
async def test_member_loop_can_submit_report_when_new_retrieval_is_blocked() -> None:
    from workflows._shared.research.observers.finalize_answer_observer import FinalizeAnswerObserver
    from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

    @tool
    async def web_fetch(url: list[str]) -> str:
        """Fake retrieval which must never execute in the handoff window."""
        raise AssertionError("new retrieval ran after the handoff cutoff")

    @tool
    async def submit_report(content: str) -> str:
        """Submit a report."""
        return "accepted"

    class HandoffLLM:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                name, args = "web_fetch", {"url": ["https://example.org/a", "https://example.org/b"]}
            else:
                assert any("research handoff window" in str(m) for m in messages)
                name, args = "submit_report", {"content": "Findings: partial evidence. Unresolved: checks."}
            return LLMResponse(content="", tool_calls=[{
                "id": f"call-{self.calls}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }], finish_reason="tool_calls")

    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(), session_name="researcher", task_id="root",
    )
    result = await run_agent_loop(
        system_prompt="research", user_message="answer using gathered evidence",
        llm=HandoffLLM(), tools=[web_fetch, submit_report],
        config=spec.config_builder("root.job.1", SubTask("research"), 4),
        observers=[
            InheritedWallClockDeadlineObserver(time.monotonic() + 60, handoff_at=time.monotonic() - 1),
            ContentAcquisitionObserver(),
            FinalizeAnswerObserver(tool_names=["submit_report"]),
        ],
    )
    assert result.stopped_by == "final_answer"
    assert "Unresolved: checks" in result.final_content
    acquired = result.metadata["content_acquisition"]
    assert len(acquired) == 2
    assert all(not source["obtained"] for source in acquired), "blocked retrieval is not evidence"
    assert all(source["last_attempt_status"] != "success" for source in acquired)


def test_report_wait_wakes_at_handoff_transition_without_guard_alerts() -> None:
    now = time.monotonic()
    budget = TeamPhaseBudget(
        started_monotonic_s=now, research_dispatch_deadline_s=now + 555,
        research_deadline_s=now + 720, publication_deadline_s=now + 900,
        finalization_deadline_s=now + 1050, state={},
    )
    assert budget.wait_deadline() == ("research", budget.research_dispatch_deadline_s)


@pytest.mark.asyncio
async def test_draining_instruction_allows_reserved_verification() -> None:
    now = time.monotonic()
    budget = TeamPhaseBudget(
        started_monotonic_s=now - 560,
        research_dispatch_deadline_s=now - 5,
        research_deadline_s=now + 160,
        publication_deadline_s=now + 340,
        finalization_deadline_s=now + 460,
        state={},
    )
    decision = await TeamPhaseBudgetObserver(budget).on_turn_end(SimpleNamespace(metadata={}))
    assert decision is not None
    assert "research or verification" not in decision.inject_messages[0]
    assert "final_verifier" in decision.inject_messages[0]


def test_web_phase_plan_reserves_a_distinct_publication_slice() -> None:
    budget = _build_team_phase_budget(
        started_monotonic_s=1_000,
        research_wall_s=720,
        publication_phase_timeout_s=180,
        hard_deadline_monotonic_s=2_050,
        finalization_timeout_s=120,
        wind_down_timeout_s=15,
        worst_case_tool_s=165,
        publication_state={},
    )

    assert budget.research_dispatch_deadline_s == 1_495
    assert budget.research_deadline_s == 1_720
    assert budget.publication_deadline_s == 1_900
    assert budget.finalization_deadline_s == 2_050


@pytest.mark.asyncio
async def test_team_phase_observer_publishes_absolute_coordinator_deadline() -> None:
    deadline = time.monotonic() + 60
    budget = TeamPhaseBudget(
        started_monotonic_s=time.monotonic(),
        research_dispatch_deadline_s=deadline - 30,
        research_deadline_s=deadline - 10,
        publication_deadline_s=deadline,
        finalization_deadline_s=deadline + 30,
        state={},
    )
    scope = ExecutionScope(task_id="task", metadata={})
    token = set_current_execution_scope(scope)
    try:
        await TeamPhaseBudgetObserver(budget).on_loop_start(LoopConfig())
    finally:
        reset_current_execution_scope(token)

    assert scope.metadata[WALL_DEADLINE_MONOTONIC_KEY] == deadline


def test_member_jobs_receive_distinct_research_verification_and_publication_deadlines() -> None:
    now = time.monotonic()
    budget = TeamPhaseBudget(
        started_monotonic_s=now,
        research_dispatch_deadline_s=now + 5,
        research_deadline_s=now + 10,
        publication_deadline_s=now + 40,
        finalization_deadline_s=now + 60,
        state={},
    )
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(phase_budget=budget),
        session_name="worker",
        task_id="task",
    )

    research = SubTask("research", metadata={"can_publish": False})
    verifier = SubTask(
        "verify",
        metadata={"can_publish": False, "uses_publication_budget": True},
    )
    publisher = SubTask("publish", metadata={"can_publish": True})
    assert spec.run_timeout_builder is not None
    research_timeout = spec.run_timeout_builder(research)
    verifier_timeout = spec.run_timeout_builder(verifier)
    publisher_timeout = spec.run_timeout_builder(publisher)

    assert research_timeout is not None
    assert verifier_timeout is not None
    assert publisher_timeout is not None
    assert 9 <= research_timeout <= 10
    assert 39 <= verifier_timeout <= 40
    assert 39 <= publisher_timeout <= 40


def test_web_team_wall_extension_is_isolated_from_single_agent() -> None:
    cfg = SimpleNamespace(wall_timeout_s=900, agent_team_wall_timeout_s=1050)

    assert _pipeline_wall_timeout_s(cfg, "agent_team") == 1050
    assert _pipeline_wall_timeout_s(cfg, "stateful-react-agent") == 900


def test_web_single_research_budget_remains_450_seconds() -> None:
    single = build_profile_overrides(pipeline_id="stateful-react-agent")["agent"]

    assert single["research_wall_time_s"] == 450
    assert single["finalization_timeout_s"] == 120
    assert single["finalization_reserve_s"] == 180
    assert single["tool_timeout_s"] == 90


def test_wind_down_uses_real_remaining_wall_not_full_llm_ceiling() -> None:
    assert _bounded_wind_down_wait_s(15, 350, now_monotonic=100) == 15
    assert _bounded_wind_down_wait_s(15, 100.5, now_monotonic=100) == 0
    assert _bounded_wind_down_wait_s(15, None, now_monotonic=100) == 15


def test_first_chunk_budget_reaches_the_member_loop_config() -> None:
    runtime = SwarmSubagentRuntime(first_chunk_timeout_s=45)
    spec = build_swarm_session_runtime_spec(
        runtime,
        session_name="researcher",
        task_id="task",
    )

    config = spec.config_builder("job-1", SubTask("research this"), 3)

    assert config.first_chunk_timeout == 45


@pytest.mark.asyncio
async def test_member_first_chunk_budget_controls_the_real_stream_wait() -> None:
    runtime = SwarmSubagentRuntime(first_chunk_timeout_s=0.02)
    spec = build_swarm_session_runtime_spec(
        runtime,
        session_name="researcher",
        task_id="task",
    )
    config = spec.config_builder("job-1", SubTask("research this"), 3)

    class SilentStreamLLM:
        async def stream(self, _messages, *, timeout=None):
            del timeout
            await asyncio.sleep(1)
            if False:
                yield None

    async def on_delta(*_args, **_kwargs) -> None:
        pass

    started = time.monotonic()
    with pytest.raises(LLMStreamStalled):
        await _stream_llm_response(
            SilentStreamLLM(),
            [],
            timeout=1,
            on_delta=on_delta,
            first_chunk_s=config.first_chunk_timeout,
        )

    assert time.monotonic() - started < 0.5


def _build_spec_under_parent_deadline(deadline: object):
    token = set_current_execution_scope(
        ExecutionScope(
            task_id="root",
            metadata={WALL_DEADLINE_MONOTONIC_KEY: deadline},
        )
    )
    try:
        return build_swarm_session_runtime_spec(
            SwarmSubagentRuntime(),
            session_name="researcher",
            task_id="task",
        )
    finally:
        reset_current_execution_scope(token)


@pytest.mark.asyncio
async def test_member_inherits_parent_deadline_and_blocks_late_tools() -> None:
    parent_deadline = time.monotonic() - 1
    spec = _build_spec_under_parent_deadline(parent_deadline)
    observers = spec.observers_builder("job-1", SubTask("research this"), 1)
    inherited = next(
        observer
        for observer in observers
        if isinstance(observer, InheritedWallClockDeadlineObserver)
    )
    member_scope = ExecutionScope(task_id="task", metadata={})
    token = set_current_execution_scope(member_scope)
    try:
        await inherited.on_loop_start(SimpleNamespace())
        tool_decision = await inherited.on_tool_call(
            SimpleNamespace(metadata={}),
            {"name": "web_search", "args": {"query": "late"}},
        )
        turn_decision = await inherited.on_turn_end(SimpleNamespace(metadata={}))
    finally:
        reset_current_execution_scope(token)

    assert member_scope.metadata[WALL_DEADLINE_MONOTONIC_KEY] is parent_deadline
    assert tool_decision is not None
    assert "deadline" in tool_decision.skip_with_result.lower()
    assert tool_decision.metadata_updates == {"team_research_deadline_reached": True}
    assert turn_decision is not None
    assert turn_decision.stop_reason == "wall_deadline"


@pytest.mark.asyncio
async def test_member_loop_does_not_start_llm_after_team_deadline() -> None:
    class NeverCalledLLM:
        model = "test"
        calls = 0

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("member LLM must not start after the deadline")

    llm = NeverCalledLLM()
    spec = _build_spec_under_parent_deadline(time.monotonic() - 1)
    config = spec.config_builder("job-1", SubTask("research this"), 3)
    inherited = next(
        observer
        for observer in spec.observers_builder(
            "job-1",
            SubTask("research this"),
            1,
        )
        if isinstance(observer, InheritedWallClockDeadlineObserver)
    )

    result = await run_agent_loop(
        system_prompt="research",
        user_message="research this",
        llm=llm,
        tools=[],
        config=config,
        observers=[inherited],
    )

    assert llm.calls == 0
    assert result.stopped_by == "wall_deadline"


@pytest.mark.asyncio
async def test_member_deadline_allows_work_before_expiry() -> None:
    spec = _build_spec_under_parent_deadline(time.monotonic() + 60)
    observers = spec.observers_builder("job-1", SubTask("research this"), 1)
    inherited = next(
        observer
        for observer in observers
        if isinstance(observer, InheritedWallClockDeadlineObserver)
    )
    token = set_current_execution_scope(ExecutionScope(task_id="task", metadata={}))
    try:
        await inherited.on_loop_start(SimpleNamespace())
        tool_decision = await inherited.on_tool_call(
            SimpleNamespace(metadata={}),
            {"name": "web_search", "args": {"query": "on time"}},
        )
        turn_decision = await inherited.on_turn_end(SimpleNamespace(metadata={}))
    finally:
        reset_current_execution_scope(token)

    assert tool_decision is None
    assert turn_decision is None


@pytest.mark.asyncio
async def test_member_guard_does_not_overwrite_an_earlier_team_deadline() -> None:
    parent_deadline = time.monotonic() + 60
    spec = _build_spec_under_parent_deadline(parent_deadline)
    inherited = next(
        observer
        for observer in spec.observers_builder(
            "job-1",
            SubTask("research this"),
            1,
        )
        if isinstance(observer, InheritedWallClockDeadlineObserver)
    )
    scope = ExecutionScope(task_id="task", metadata={})
    token = set_current_execution_scope(scope)
    try:
        await inherited.on_loop_start(LoopConfig())
        await WallClockGuard(budget_s=1_000).on_loop_start(LoopConfig())
    finally:
        reset_current_execution_scope(token)

    assert scope.metadata[WALL_DEADLINE_MONOTONIC_KEY] is parent_deadline


@pytest.mark.asyncio
async def test_member_recovery_skips_llm_after_team_deadline() -> None:
    class RecordingLLM:
        calls = 0

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("recovery LLM must not start after the deadline")

    llm = RecordingLLM()
    token = set_current_execution_scope(
        ExecutionScope(
            task_id="root",
            metadata={WALL_DEADLINE_MONOTONIC_KEY: time.monotonic() - 1},
        )
    )
    try:
        spec = build_swarm_session_runtime_spec(
            SwarmSubagentRuntime(sub_agent_llm=llm),
            session_name="researcher",
            task_id="task",
        )
    finally:
        reset_current_execution_scope(token)

        result = AgentLoopResult(
            messages=[{"role": "user", "content": "research this"}],
            stopped_by="wall_deadline",
        )
    finalized = await spec.force_finalizer(result, SubTask("research this"))

    assert llm.calls == 0
    assert finalized.metadata["final_answer_rescue_mode"] == "deterministic_fallback"
    assert finalized.final_content


@pytest.mark.asyncio
async def test_member_llm_error_is_delivered_without_a_second_model_call() -> None:
    class RecordingLLM:
        calls = 0

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("a failed member call must not be retried during handoff")

    llm = RecordingLLM()
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(sub_agent_llm=llm),
        session_name="researcher",
        task_id="task",
    )
    result = AgentLoopResult(
        messages=[{"role": "user", "content": "research this"}],
        stopped_by="llm_error",
    )

    finalized = await spec.force_finalizer(result, SubTask("research this"))

    assert llm.calls == 0
    assert finalized.metadata["final_answer_rescue_mode"] == "deterministic_fallback"
    assert finalized.final_content


@pytest.mark.asyncio
async def test_member_recovery_has_a_small_handoff_budget_without_job_deadline() -> None:
    class HangingLLM:
        calls = 0
        cancelled = False

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    llm = HangingLLM()
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(
            sub_agent_llm=llm,
            sub_agent_llm_timeout=10,
            sub_agent_recovery_timeout_s=0.03,
        ),
        session_name="researcher",
        task_id="task",
    )
    result = AgentLoopResult(
        messages=[
            {"role": "user", "content": "research this"},
            {"role": "assistant", "content": "Partial finding worth preserving."},
        ],
        stopped_by="wall_deadline",
    )

    started = time.monotonic()
    finalized = await spec.force_finalizer(result, SubTask("research this"))

    assert time.monotonic() - started < 0.5
    assert llm.calls == 1
    assert llm.cancelled is True
    assert finalized.metadata["final_answer_rescue_mode"] == "deterministic_fallback"


@pytest.mark.asyncio
async def test_member_without_evidence_skips_recovery_even_for_recoverable_stop() -> None:
    class RecordingLLM:
        calls = 0

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("there is no evidence for a recovery synthesis")

    llm = RecordingLLM()
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(sub_agent_llm=llm),
        session_name="researcher",
        task_id="task",
    )
    result = AgentLoopResult(
        messages=[{"role": "user", "content": "research this"}],
        stopped_by="wall_deadline",
    )

    finalized = await spec.force_finalizer(result, SubTask("research this"))

    assert llm.calls == 0
    assert finalized.metadata["final_answer_rescue_mode"] == "deterministic_fallback"


@pytest.mark.asyncio
async def test_member_deadline_preserves_latest_tool_calculation() -> None:
    class RecordingLLM:
        calls = 0

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("recovery LLM must not start after the deadline")

    llm = RecordingLLM()
    token = set_current_execution_scope(
        ExecutionScope(
            task_id="root",
            metadata={WALL_DEADLINE_MONOTONIC_KEY: time.monotonic() - 1},
        )
    )
    try:
        spec = build_swarm_session_runtime_spec(
            SwarmSubagentRuntime(sub_agent_llm=llm),
            session_name="auditor",
            task_id="task",
        )
    finally:
        reset_current_execution_scope(token)

    result = AgentLoopResult(
        messages=[
            {"role": "user", "content": "calculate the complete CSV"},
            tool_msg("eligible=7 gross=941 refund=138 net=803", "bash-1"),
        ],
        final_content="",
        stopped_by="wall_deadline",
    )
    finalized = await spec.force_finalizer(result, SubTask("calculate the complete CSV"))

    assert llm.calls == 0
    assert "eligible=7 gross=941 refund=138 net=803" in finalized.final_content
    assert finalized.metadata["final_answer_rescue_mode"] == "tool_observations"


@pytest.mark.asyncio
async def test_member_recovery_is_cancelled_at_team_deadline() -> None:
    class HangingLLM:
        calls = 0
        cancelled = False

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    llm = HangingLLM()
    token = set_current_execution_scope(
        ExecutionScope(
            task_id="root",
            metadata={WALL_DEADLINE_MONOTONIC_KEY: time.monotonic() + 0.03},
        )
    )
    try:
        spec = build_swarm_session_runtime_spec(
            SwarmSubagentRuntime(sub_agent_llm=llm, sub_agent_llm_timeout=10),
            session_name="researcher",
            task_id="task",
        )
    finally:
        reset_current_execution_scope(token)

    result = AgentLoopResult(
        messages=[
            {"role": "user", "content": "research this"},
            {"role": "assistant", "content": "Partial finding worth preserving."},
        ],
        stopped_by="wall_deadline",
    )
    started = time.monotonic()
    finalized = await spec.force_finalizer(result, SubTask("research this"))

    assert time.monotonic() - started < 0.5
    assert llm.calls == 1
    assert llm.cancelled is True
    assert finalized.metadata["final_answer_rescue_mode"] == "deterministic_fallback"
