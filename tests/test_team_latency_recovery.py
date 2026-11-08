"""Regressions from c117: blocked retrieval, runaway verification and lost repair time."""

import importlib
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

from frontier_agent.components.agent_bus import SubTask
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.runtime.loop._call import call_llm
from frontier_agent.core.runtime.loop.tool_exec import execute_tools
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from tests.test_team_verification_admission import admission_run as _admission_run
from workflows.agent_team.delivery import TeamDeliveryObserver
from workflows.agent_team.subagent_runtime import (
    SwarmSubagentRuntime,
    build_swarm_session_runtime_spec,
)

delivery_run = _delivery_run
admission_run = _admission_run


async def test_searches_overlap_and_preserve_task_context(monkeypatch):
    module = importlib.import_module("plugins.tools.corpus_search")
    barrier = threading.Barrier(2, timeout=0.3)
    observed = []

    class Backend:
        def search_with_coverage(self, query, *, limit):
            observed.append(module._market_redirect.get())
            barrier.wait()
            return [], {"processing": "complete", "availability": "unknown"}

    monkeypatch.setattr(module, "get_service", lambda: Backend())
    token = module.set_market_redirect(False)
    try:
        results = await execute_tools(
            [{"name": "corpus_search", "args": {"query": q}} for q in ("first", "second")],
            {"corpus_search": module.corpus_search}, timeout=2, turn=1, count_offset=0,
        )
    finally:
        module.reset_market_redirect(token)
    assert all(not r.is_error for r in results), "synchronous searches serialized the shared loop"
    assert observed == [False, False], "thread handoff must preserve per-member corpus policy"


def test_verifier_has_bounded_recovery_without_changing_research_policy():
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(reasoning_only_timeout_s=120, logical_call_timeout_s=180),
        session_name="review", task_id="run",
    )
    checked = spec.config_builder("v", SubTask("verify", metadata={
        "verification_checks": [{"check_id": "a"}, {"check_id": "b"}],
    }), 200)
    research = spec.config_builder("r", SubTask("research"), 200)
    assert checked.reasoning_only_timeout_s <= 25
    assert checked.logical_call_timeout_s <= 90
    assert checked.reasoning_max_retries == 0
    assert checked.max_turns <= 6
    assert research.reasoning_only_timeout_s == 120
    assert research.logical_call_timeout_s == 180


async def test_zero_reasoning_resamples_returns_control_without_replaying():
    class Client:
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert kwargs["max_tokens"] == 8192
            return LLMResponse(content="", reasoning_content="thinking", finish_reason="length")

    client = Client()
    response = await call_llm(client, [], 30, 5, 1, reasoning_max_retries=0, request_max_tokens=8192)
    assert response is not None
    assert client.calls == 1


async def test_c117_failed_check_can_use_spare_time_before_delivery_reserve(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    # Actual c117 boundaries: first-pass verification 734, publication 914.
    budget = replace(budget, verification_deadline_s=734, publication_deadline_s=914)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 680)
    observer = TeamDeliveryObserver(budget)
    decision = await observer.on_before_llm(turn_context())
    assert not observer.active
    assert "[team verification repair]" in " ".join(decision.inject_messages)
    assert budget.deadline_for_job(can_publish=False, is_verification=True, is_recheck=True) == 794


async def test_verification_checkpoints_one_validated_check_at_a_time():
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.submit_report import submit_report
    from tests.test_agent_team_verification import binding, verdict_for
    from workflows.agent_team.observers.member_progress import MemberProgressObserver

    checks = [binding(check_id="one", version="a" * 64), binding(check_id="two", version="b" * 64)]
    metadata = {"verification_checks": checks}
    token = set_verification_scope("review", metadata)
    observer = MemberProgressObserver(metadata)
    try:
        for i, check in enumerate(checks):
            iv = await observer.on_before_llm(SimpleNamespace())
            assert check["check_id"] in iv.inject_messages[0]
            call = {"name": "submit_report", "args": {"content": "Scope: amount. Finding: 50.",
                    "verification_results": [verdict_for(check)]}}
            decision = await observer.on_tool_call(SimpleNamespace(), call)
            assert decision.rewrite_args["finish"] is (i == 1)
            await submit_report.func(**decision.rewrite_args)
            assert len(metadata["verification_events"]) == i + 1
    finally:
        reset_verification_scope(token)


async def test_source_count_and_elapsed_time_do_not_trigger_completion(monkeypatch):
    from workflows.agent_team.observers.member_progress import MemberProgressObserver

    monkeypatch.setattr(time, "monotonic", lambda: 0)
    observer = MemberProgressObserver({})
    context = SimpleNamespace(metadata={"corpus_evidence": [
        {"doc_id": "doc", "locator": "one"}, {"doc_id": "doc", "locator": "two"},
    ]})
    monkeypatch.setattr(time, "monotonic", lambda: 100)
    assert await observer.on_before_llm(context) is None


async def test_malformed_checkpoint_returns_tool_error_without_crashing_observer():
    from tests.test_agent_team_verification import binding
    from workflows.agent_team.observers.member_progress import MemberProgressObserver

    observer = MemberProgressObserver({"verification_checks": [binding(check_id="one")]})
    for results in (["invalid"], {"check_id": "one"}, 1):
        decision = await observer.on_tool_call(SimpleNamespace(), {
            "name": "submit_report", "args": {"verification_results": results},
        })
        assert decision.skip_is_error
        assert "one" in decision.skip_with_result


async def test_live_reasoning_abort_does_not_resample_inside_verifier_call(monkeypatch):
    from frontier_agent.core.errors import LLMReasoningRunaway
    from frontier_agent.core.runtime.loop import _call

    calls = []
    async def stream(*args, **kwargs):
        calls.append(kwargs)
        raise LLMReasoningRunaway(elapsed_s=25, estimated_tokens=3000, trigger="time",
                                 partial_response=LLMResponse(content="", reasoning_content="thinking"))
    async def delta(*args, **kwargs):
        pass
    monkeypatch.setattr(_call, "_stream_llm_response", stream)
    state = {}
    await call_llm(object(), [], 90, 5, 1, on_delta=delta, runaway_state=state,
                   reasoning_only_timeout_s=25, reasoning_max_retries=0)
    assert len(calls) == 1
    assert state["last_call_retry_blocked_by"] == "runaway_retry_limit"


async def test_checkpoint_finish_rewrite_survives_real_agent_loop():
    from frontier_agent.core.loop_types import LoopConfig
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.submit_report import submit_report
    from tests.test_agent_team_verification import binding, verdict_for
    from workflows._shared.research.observers.finalize_answer_observer import FinalizeAnswerObserver
    from workflows.agent_team.observers.member_progress import MemberProgressObserver

    checks = [binding(check_id="one", version="a" * 64), binding(check_id="two", version="b" * 64)]
    metadata = {"verification_checks": checks}
    class Client:
        calls = 0
        async def chat(self, messages, **kwargs):
            check = checks[self.calls]
            assert len(metadata["verification_events"]) == self.calls
            self.calls += 1
            return LLMResponse(content="", tool_calls=[{
                "id": f"c{self.calls}", "name": "submit_report", "args": {
                    "content": "Scope: amount. Finding: 50.", "finish": True,
                    "verification_results": [verdict_for(check)],
                },
            }])
    token = set_verification_scope("review", metadata)
    try:
        result = await run_agent_loop(system_prompt="Check", user_message="Review", llm=Client(),
            tools=[submit_report], config=LoopConfig(max_turns=3), observers=[
                MemberProgressObserver(metadata), FinalizeAnswerObserver(tool_names=["submit_report"]),
            ])
        assert result.stopped_by == "final_answer"
        assert len(metadata["verification_events"]) == 2
    finally:
        reset_verification_scope(token)


async def test_recheck_admission_execution_and_collection_share_extended_deadline(admission_run, tmp_path):
    from plugins.tools._verification import VerificationCheck, bind_checks
    from plugins.tools.assign_task import agent_team_assign_task
    from plugins.tools.collect_reports import collect_reports
    from plugins.tools.task_board import add_task, snapshot_tasks
    from tests.test_agent_team_verification import add_job
    from workflows.agent_team.phase_budget import TeamPhaseBudget

    bus, runtime = admission_run
    await add_task.func([{"description": "Check", "kind": "verification", "owners": ["reviewer"],
        "verification_requirements": [{"check_id": "amount", "criterion": "Check amount"}]}])
    add_job(bus, "source", [])
    spec = VerificationCheck(check_id="amount", work_item_id="t1", criterion="Check amount",
                             subject={"text": "bad"}, evidence=[{"job_id": "source"}])
    checks, _ = bind_checks([spec], bus=bus, task_id="run", work_items=snapshot_tasks("run"),
                            required=True, outputs_root=tmp_path)
    add_job(bus, "failed", checks, verdicts=["fail"])
    now = time.monotonic()
    budget = TeamPhaseBudget(now - 680, now - 351, now - 126, now + 234, now + 370, {},
                             verification_deadline_s=now + 54)
    from frontier_agent.core.execution_context import get_current_execution_scope
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    runtime = replace(runtime, phase_budget=budget)
    get_current_execution_scope().metadata[SWARM_SCOPE_KEY] = runtime
    bus.list_sessions_for_task("run")[0].runtime_spec = build_swarm_session_runtime_spec(
        runtime, session_name="reviewer", task_id="run",
    )
    revision = {**spec.model_dump(), "subject": {"text": "corrected"},
                "replaces_job_id": "failed", "revision_kind": "subject", "revision_reason": "Fix scope"}
    reply = await agent_team_assign_task.func(tasks=[{"agent": "reviewer", "prompt": "Check correction",
                                                      "verification_checks": [revision]}])
    assert not reply.startswith("Error"), reply
    job = bus.list_task_jobs("run")[-1]
    session_spec = build_swarm_session_runtime_spec(runtime, session_name="reviewer", task_id="run")
    assert 110 < session_spec.run_timeout_builder(job.item) <= 114
    assert budget.wait_deadline(verification_pending=True, recheck_pending=True)[1] == now + 114
    await collect_reports.func(timeout=2)
    assert snapshot_tasks("run")[0]["verification_status"] == "passed"
