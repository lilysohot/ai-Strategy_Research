"""Run-local failures cross members; delivered evidence never does."""

import json

from plugins.corpus.progress import CorpusProgressObserver, CorpusReadState
from tests.test_corpus_progress import context, fetch, turn
from workflows.agent_team.subagent_runtime import SwarmSubagentRuntime


async def test_revocation_crosses_members_and_coordinator_even_if_body_is_omitted():
    runtime = SwarmSubagentRuntime()
    reader = CorpusProgressObserver(read_state=runtime.corpus_read_state, stop_after=6)
    coordinator = CorpusProgressObserver(read_state=runtime.corpus_read_state)
    other_run = SwarmSubagentRuntime()
    failure = {
        "ok": False, "doc_id": "doc", "code": "withdrawn",
        "retryable": False, "failure_scope": "document",
    }
    await turn(reader, context(), "corpus_fetch", failure, delivered="{omitted")
    replacement = CorpusProgressObserver(read_state=runtime.corpus_read_state)
    for observer in (coordinator, replacement):
        for name in ("corpus_fetch", "corpus_inventory"):
            denied = await observer.on_tool_call(context(), {
                "name": name, "args": {"doc_id": "doc", "force_refresh": True},
            })
            assert json.loads(denied.skip_with_result)["execution_suppressed"]
            assert denied.skip_is_error
        assert not observer.seen and observer.streak == 0
    assert not other_run.corpus_read_state.withdrawn
    assert await CorpusProgressObserver(read_state=other_run.corpus_read_state).on_tool_call(
        context(), {"name": "corpus_fetch", "args": {"doc_id": "doc"}},
    ) is None


async def test_transient_failures_and_member_evidence_are_not_shared_denials():
    state = CorpusReadState()
    first = CorpusProgressObserver(read_state=state)
    second = CorpusProgressObserver(read_state=state)
    await turn(first, context(), "corpus_fetch", fetch())
    await turn(first, context(), "corpus_fetch", {
        "ok": False, "doc_id": "doc", "code": "fetch_failed", "retryable": True,
        "error": "withdrawn appears in prose only",
    })
    assert first.seen and not second.seen and not state.withdrawn
    await turn(second, context(), "corpus_fetch", fetch())
    assert second.new_observations == 1 and second.repeated_calls == 0


def test_coordinator_builder_uses_supplied_run_state(tmp_path):
    from workflows.agent_team.nodes.main_agent import _build_observers

    state = CorpusReadState()
    observers = _build_observers(
        traj_dir=tmp_path, task_id="run", budget_tokens=None, max_input_tokens=None,
        event_store=None, tool_names=[], corpus_read_state=state,
    )
    observer = next(o for o in observers if isinstance(o, CorpusProgressObserver))
    assert observer.read_state is state


def test_new_member_jobs_use_same_run_state_with_independent_progress():
    from frontier_agent.components.agent_bus.models import SubTask
    from workflows.agent_team.subagent_runtime import build_swarm_session_runtime_spec

    runtime = SwarmSubagentRuntime()
    members = []
    for name in ("reader", "verifier"):
        spec = build_swarm_session_runtime_spec(runtime, session_name=name, task_id="run")
        for index in (1, 2):
            observers = spec.observers_builder(f"{name}-{index}", SubTask("Read source"), index)
            members.append(next(o for o in observers if isinstance(o, CorpusProgressObserver)))
    assert all(o.read_state is runtime.corpus_read_state for o in members)
    assert len({id(o.seen) for o in members}) == 4


def test_original_80_benchmark_cases_remain_unchanged():
    from pathlib import Path

    from benchmarks.team_workflow.run import catalog, digest

    root = Path(__file__).resolve().parents[1] / "benchmarks/team_workflow"
    baseline = json.loads((root / "baseline-80.lock.json").read_text())["cases"]
    current = {c["id"]: c for c in catalog()}
    assert len(baseline) == 80
    assert set(current) - set(baseline) == {"P56", "P57", "P58"}
    for key, expected in baseline.items():
        assert digest(current[key]) == expected
