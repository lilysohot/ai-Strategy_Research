"""Regressions from the 034f3c / 5eb55f same-question Web runs."""

from __future__ import annotations

import json
from types import SimpleNamespace

from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, tool_msg
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.subagent_runtime import (
    _build_recovery_messages,
    _stitch_recent_tool_observations,
    force_final_answer,
)


def observed(call_id, url, body):
    return [
        assistant_msg(
            "",
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "arguments": json.dumps({"url": url}),
                    },
                }
            ],
        ),
        tool_msg(body, call_id),
    ]


def conflicting_history():
    messages = observed("original", "https://primary.example/model", "Index = 32. " + "a" * 7000)
    for n in range(12):
        messages += observed(f"noise-{n}", f"https://other.example/{n}", "noise " * 1100)
    messages += observed("retelling", "https://blog.example/review", "Index = 45. " + "b" * 7700)
    return messages


def test_deadline_salvage_keeps_early_source_and_conflicting_late_retelling():
    text = _stitch_recent_tool_observations(conflicting_history())
    assert "Index = 32" in text and "Index = 45" in text
    assert "https://primary.example/model" in text
    assert "https://blog.example/review" in text
    assert "original" in text and "retelling" in text
    assert len(text) <= 41_000


def test_coordinator_recovery_preserves_both_sources_after_member_handoff():
    report = _stitch_recent_tool_observations(conflicting_history())
    messages = [tool_msg(f'<report agent="researcher" status="failed">{report}</report>', "fan-in")]
    prompt = _build_recovery_messages(
        messages, task_description="Compare models", structured_report=False
    )
    text = str(prompt)
    assert "Index = 32" in text and "Index = 45" in text
    assert "https://primary.example/model" in text and "https://blog.example/review" in text


async def test_recovery_strips_unexecuted_board_mutation_without_running_it(monkeypatch):
    from workflows.agent_team import subagent_runtime as runtime

    async def answer(*args, **kwargs):
        return SimpleNamespace(
            content='<update_task>tasks=[{"id":"t4","status":"resolved"}]</update_task>\nAnswer.',
            reasoning_content="",
        )

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", answer)
    result = AgentLoopResult(messages=[tool_msg("some evidence", "c1")], stopped_by="wall_deadline")
    await force_final_answer(result, object(), 1, task_description="Compare models")
    assert result.final_content == "Answer."


def test_normal_final_report_strips_board_leak_but_preserves_code_example():
    example = "Example:\n```xml\n<update_task>tasks=[]</update_task>\n```"
    out = finalize_team_report(
        '<update_task>tasks=[{"id":"t4"}]</update_task>\nAnswer.\n' + example,
        source="agent",
        answer_status="partial",
        stopped_by="final_answer",
        question="Explain",
        language="English",
        wind_down={},
        tasks=[{"id": "t4", "description": "Check sources", "resolution": "in_progress"}],
    )
    assert 'tasks=[{"id":"t4"}]' not in out["final_answer"]
    assert example in out["final_answer"]
    assert out["answer_status"] == "partial"


async def test_cancelled_trajectory_flushes_terminal_snapshot(tmp_path):
    from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
    from frontier_agent.core.loop_types import LoopConfig, TurnContext

    observer = TrajectoryFileObserver(tmp_path, filename="member")
    await observer.on_loop_start(LoopConfig(task_id="r", role_id="worker", max_turns=20))
    ctx = TurnContext(
        turn=3,
        max_turns=20,
        task_id="r",
        role_id="worker",
        ai_text="last observation",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )
    await observer.on_llm_response(ctx)
    await observer.on_loop_cancelled()
    snap = json.loads((tmp_path / "member.json").read_text())
    events = [json.loads(line) for line in (tmp_path / "member.jsonl").read_text().splitlines()]
    assert snap["turns_used"] == 3
    assert snap["stopped_by"] == "cancelled"
    assert events[-1]["t"] == "end" and events[-1]["stopped_by"] == "cancelled"


async def test_recovery_trace_is_discovered_and_included_in_web_usage(tmp_path, monkeypatch):
    from frontier_agent.core.llm import LLMResponse
    from server import relay, usage
    from server.trajectory_sources import discover_trajectory_sources
    from workflows.agent_team import subagent_runtime as runtime

    async def answer(*args, **kwargs):
        return LLMResponse(
            content="Answer.",
            model="test-model",
            usage={
                "prompt_tokens": 23,
                "completion_tokens": 7,
            },
        )

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", answer)
    monkeypatch.setattr(usage, "run_dir_for", lambda _: tmp_path)
    monkeypatch.setattr(relay, "run_dir_for", lambda _: tmp_path)
    root = tmp_path / "run/agent/trajectories"
    result = AgentLoopResult(messages=[tool_msg("evidence", "c")], stopped_by="wall_deadline")
    await force_final_answer(
        result, object(), 1, recovery_trace_path=root / "main_finalization.jsonl"
    )
    assert discover_trajectory_sources(tmp_path)[0].source == "main_finalization"
    totals = usage.usage_for_run("run")
    assert totals["prompt_tokens"] == 23 and totals["completion_tokens"] == 7
    assert totals["llm_calls"] == 1 and totals["status"] == "complete"
    assert result.metadata["recovery_calls"][0]["usage_status"] == "reported"
    snapshot = json.loads((root / "main_finalization.json").read_text())
    assert snapshot["stopped_by"] == "recovery_complete"
    # One unmetered turn must make the aggregate partial even if another turn
    # did report usage; missing provider usage is not a confirmed zero.
    (root / "main_agent.jsonl").write_text(json.dumps({"t": "llm", "turn": 1}) + "\n")
    assert usage.usage_for_run("run")["status"] == "partial"
    assert usage.usage_for_run("run")["unmetered_calls"] == 1


async def test_recovery_failure_is_terminal_and_usage_stays_unknown(tmp_path, monkeypatch):
    from workflows.agent_team import subagent_runtime as runtime

    async def fail(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", fail)
    result = AgentLoopResult(messages=[tool_msg("evidence", "c")], stopped_by="wall_deadline")
    await force_final_answer(result, object(), 1, recovery_trace_path=tmp_path / "rescue.jsonl")
    events = [json.loads(line) for line in (tmp_path / "rescue.jsonl").read_text().splitlines()]
    assert events[-1]["stopped_by"] == "recovery_failed"
    assert result.metadata["recovery_calls"][0]["usage_status"] == "unavailable"


async def test_partial_without_new_evidence_does_not_regenerate_latched_answer(monkeypatch):
    from workflows.agent_team import subagent_runtime as runtime
    from workflows.agent_team.lifecycle import TeamWindDown, append_team_wind_down_checkpoint

    async def unexpected(*args, **kwargs):
        raise AssertionError("No new evidence warrants another model call")

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", unexpected)
    wind = TeamWindDown("partial", "Checks remain unchecked", 0, 1, 0, 0)
    result = AgentLoopResult(
        messages=[],
        final_content="Evidence-based draft; limitations disclosed.",
        stopped_by="final_answer",
        metadata={"final_answer": "latched"},
    )
    append_team_wind_down_checkpoint(result, wind)
    await force_final_answer(result, object(), 1, force_recovery=wind.should_refresh_answer(result))
    assert result.final_content == "Evidence-based draft; limitations disclosed."
    assert result.metadata["team_wind_down"]["run_status"] == "partial"
    assert "recovery_calls" not in result.metadata


def test_large_fan_in_preserves_last_members_counterevidence():
    from frontier_agent.core.messages import tool_msg
    from workflows.agent_team.subagent_runtime import _stitch_collected_reports
    first = '<report agent="first" job="j1" status="incomplete">' + "x" * 60000 + '</report>'
    second = ('<report agent="second" job="j2" status="incomplete">'
              'COUNTEREVIDENCE https://example.org/training' + "y" * 10000 + '</report>')
    text = _stitch_collected_reports([tool_msg(first, "c1"), tool_msg(second, "c2")])
    assert 'COUNTEREVIDENCE https://example.org/training' in text
    assert 'agent="second"' in text
    assert len(text) < 61000
