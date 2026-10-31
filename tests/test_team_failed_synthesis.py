"""A completed fan-in must survive failed synthesis (e93366d1)."""

import json

from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, tool_msg
from server.cache_metrics import cache_stats_for_directory
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.subagent_runtime import _build_recovery_messages, force_final_answer


async def test_failed_synthesis_publishes_collected_findings_not_tool_preamble(monkeypatch):
    from workflows.agent_team import subagent_runtime as runtime

    async def fail(*args, **kwargs):
        raise TimeoutError("offline reproduction")

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", fail)
    progress = "Two researchers done; one is still running — let me collect it."
    messages = [assistant_msg(progress, tool_calls=[{
        "id": "collect", "type": "function",
        "function": {"name": "collect_reports", "arguments": "{}"},
    }])]
    for i in range(3):
        messages.append(tool_msg(
            f'<report agent="member{i}" job="j{i}" status="complete">'
            f'Finding {i}: https://example.org/{i}. Gap {i}: unverified.</report>',
            "collect",
        ))
    result = AgentLoopResult(
        messages=messages, final_content=progress, stopped_by="llm_error",
        metadata={"team_wind_down": {"collected_count": 0}},
    )
    await force_final_answer(result, object(), 1, task_description="研究结论")
    published = finalize_team_report(
        result.final_content, source=result.metadata["final_answer_source"],
        answer_status="best_effort", stopped_by=result.stopped_by, question="研究结论",
    )
    assert progress not in published["final_answer"]
    for i in range(3):
        assert f"Finding {i}" in published["final_answer"]
        assert f"Gap {i}: unverified" in published["final_answer"]
        assert f"https://example.org/{i}" in published["final_answer"]
    assert '<report ' not in published["final_answer"]
    assert published["answer_status"] == "best_effort"
    assert published["report_contract"]["source"] == "system"


async def test_failed_recovery_has_separate_logical_call_cache_statistics(tmp_path, monkeypatch):
    from workflows.agent_team import subagent_runtime as runtime

    async def fail(*args, **kwargs):
        raise TimeoutError("offline reproduction")

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", fail)
    result = AgentLoopResult(messages=[tool_msg("evidence", "c")], stopped_by="llm_error")
    path = tmp_path / "run/agent/trajectories/main_finalization.jsonl"
    await force_final_answer(result, object(), 1, recovery_trace_path=path)
    stats = cache_stats_for_directory(tmp_path)
    assert stats["recovery_calls"]["attempts"] == 1
    assert stats["recovery_calls"]["unknown_usage_attempts"] == 1
    assert stats["recovery_calls"]["unknown_duration_attempts"] == 0
    assert stats["first_attempts"]["attempts"] == 0
    assert stats["all_attempts"]["attempts"] == 0
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(e.get("t") == "recovery" and e.get("phase") == "finished" for e in events)


def test_recovery_input_does_not_repeat_reports_or_old_tool_preambles():
    progress = "Let me collect the remaining researcher."
    messages = [
        {"role": "user", "content": "Constraint: compare the same year."},
        assistant_msg(progress, tool_calls=[{"id": "c", "name": "collect_reports"}]),
        tool_msg('<report agent="r" job="j" status="complete">UNIQUE_FINDING</report>', "c"),
    ]
    text = _build_recovery_messages(messages, task_description="Compare", structured_report=False)[0]["content"]
    assert text.count("UNIQUE_FINDING") == 1
    assert progress not in text
    assert "Constraint: compare the same year." in text
