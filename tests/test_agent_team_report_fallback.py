"""Terminal fallback preserves completed member research, not failure receipts."""

import pytest

from frontier_agent.components.agent_bus import (
    AgentBus,
    JobEntry,
    SubAgentResult,
    SubTask,
)
from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import tool_msg
from workflows.agent_team.lifecycle import snapshot_member_reports
from workflows.agent_team.subagent_runtime import (
    _STITCH_MAX_CHARS,
    _collected_report_fallback,
    force_final_answer,
)


def _research(
    job_id: str,
    body: str,
    *,
    agent: str = "researcher",
    status: str = "complete",
    work_item_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "agent": agent,
        "status": status,
        "reason": "" if status == "complete" else "llm_error",
        "kind": "research",
        "content": body,
        "work_item_ids": work_item_ids or [],
        "verification_checks": [],
        "verification_events": [],
    }


def _verification(job_id: str = "root.job.3") -> dict[str, object]:
    return {
        "job_id": job_id,
        "agent": "quote_verify_verification",
        "status": "incomplete",
        "reason": "llm_error",
        "kind": "verification",
        "content": '{"verification_results":[{"check_id":"quote_fidelity","verdict":"fail"}]}',
        "work_item_ids": [],
        "verification_checks": [
            {
                "check_id": "quote_fidelity",
                "work_item_id": "t3",
                "work_item_ids": ["t3"],
                "binding_id": "a" * 64,
                "required": True,
            },
            {
                "check_id": "number_scope",
                "work_item_id": "t3",
                "work_item_ids": ["t3"],
                "binding_id": "b" * 64,
                "required": True,
            },
        ],
        "verification_events": [
            {
                "check_id": "quote_fidelity",
                "binding_id": "a" * 64,
                "verdict": "fail",
                "unresolved_issues": [
                    "引文1 not verbatim: locator ce:848f7a43e69503c22c8edf037bc1f10e"
                ],
                "job_id": job_id,
            }
        ],
    }


def _report_block(
    job_id: str, body: str, *, agent: str = "member", status: str = "complete"
) -> dict:
    return tool_msg(
        f'<report agent="{agent}" job="{job_id}" status="{status}">{body}</report>',
        "call",
    )


def _bus_with_jobs() -> AgentBus:
    bus = AgentBus()
    jobs = [
        ("root.job.1", "corpus_extract_research", "BODY ONE", ["t1"]),
        ("root.job.2", "spacex_analysis_research", "BODY TWO", ["t2"]),
    ]
    for job_id, agent, body, work_items in jobs:
        entry = JobEntry(
            job_id=job_id,
            parent_task_id="root",
            item=SubTask(
                question="q",
                role_id="agent_team_sub",
                metadata={"bound_research": True, "work_item_ids": work_items},
            ),
            task=None,
            status="completed",
            session_id=f"root::{agent}",
        )
        entry.result = SubAgentResult(
            question="q",
            role_id="agent_team_sub",
            final_content=body,
            success=True,
            job_id=job_id,
            metadata={"stopped_by": "final_answer", "final_answer_source": "agent"},
        )
        bus._jobs[job_id] = entry
    verification = JobEntry(
        job_id="root.job.3",
        parent_task_id="root",
        item=SubTask(
            question="verify",
            role_id="agent_team_sub",
            metadata={
                "verification_checks": _verification()["verification_checks"],
                "verification_events": _verification()["verification_events"],
            },
        ),
        task=None,
        status="running",
        session_id="root::quote_verify_verification",
    )
    verification.result = SubAgentResult(
        question="verify",
        role_id="agent_team_sub",
        final_content="## Tool observations preserved at the team deadline",
        success=True,
        job_id="root.job.3",
        metadata={"stopped_by": "llm_error", "final_answer_source": "tool_observations"},
    )
    bus._jobs["root.job.3"] = verification
    return bus


@pytest.mark.asyncio
async def test_records_keep_two_research_reports_when_context_has_only_verification() -> None:
    records = snapshot_member_reports(_bus_with_jobs(), "root")
    assert [record["kind"] for record in records] == [
        "research",
        "research",
        "verification",
    ]
    messages = [
        _report_block(
            "root.job.3",
            '{"verification_results":[{"check_id":"quote_fidelity","verdict":"fail"}]}',
            agent="quote_verify_verification",
            status="incomplete",
        )
    ]

    output = _collected_report_fallback(messages, records)

    assert "BODY ONE" in output and "BODY TWO" in output
    assert output.count("BODY ONE") == 1 and output.count("BODY TWO") == 1
    assert '"verification_results"' not in output
    assert "quote_fidelity: fail" in output
    assert "number_scope: unchecked" in output
    assert "ce:" not in output


def test_record_and_message_report_appear_once() -> None:
    records = [_research("root.job.1", "SAME BODY")]
    messages = [_report_block("root.job.1", "SAME BODY")]

    output = _collected_report_fallback(messages, records)

    assert output.count("SAME BODY") == 1
    assert output.count("root.job.1") == 1


def test_missing_record_is_filled_from_message() -> None:
    records = [_research("root.job.2", "SECOND BODY")]
    messages = [_report_block("root.job.1", "MESSAGE BODY")]

    output = _collected_report_fallback(messages, records)

    assert "MESSAGE BODY" in output and "SECOND BODY" in output
    assert "root.job.1 / complete / 类型未确认" in output
    assert "未取得可用正文的任务" not in output


def test_no_research_body_is_explicit_and_raw_verification_is_not_a_report() -> None:
    records = [_verification()]
    messages = [
        _report_block(
            "root.job.3",
            '{"verification_results":[{"check_id":"quote_fidelity","verdict":"fail"}]}',
            agent="quote_verify_verification",
            status="incomplete",
        )
    ]

    output = _collected_report_fallback(messages, records)

    assert "没有找到可用的成员研究报告正文" in output
    assert '"verification_results"' not in output
    assert "quote_fidelity: fail" in output
    assert "number_scope: unchecked" in output


def test_partial_report_keeps_its_incomplete_status() -> None:
    records = [_research("root.job.1", "PARTIAL BODY", status="incomplete")]

    output = _collected_report_fallback([], records)

    assert "root.job.1 / incomplete" in output
    assert "以下为已提交的部分报告" in output
    assert "PARTIAL BODY" in output


def test_tool_receipt_is_not_published_as_research() -> None:
    records = [
        {
            "job_id": "root.job.9",
            "agent": "worker",
            "status": "incomplete",
            "reason": "llm_error",
            "kind": "tool_receipt",
            "content": "## Tool observations preserved at the team deadline\nraw tail",
        }
    ]

    output = _collected_report_fallback([], records)

    assert "Tool observations preserved" not in output
    assert "没有找到可用的成员研究报告正文" in output


def test_research_body_is_kept_while_fail_and_unchecked_are_reported_as_limits() -> None:
    records = [
        _research("root.job.1", "AFFECTED BODY", work_item_ids=["t3"]),
        _research("root.job.2", "UNAFFECTED BODY", work_item_ids=["t1"]),
        _verification(),
    ]

    output = _collected_report_fallback([], records)

    assert "AFFECTED BODY" in output and "UNAFFECTED BODY" in output
    assert output.count("> 限制：") == 1
    assert "quote_fidelity=fail" in output
    assert "number_scope=unchecked" in output
    assert "AFFECTED BODY" in output.split("> 限制：", 1)[1]
    assert '"verification_checks"' not in output


@pytest.mark.asyncio
async def test_terminal_fallback_publishes_reports_after_recovery_failure(
    monkeypatch,
) -> None:
    from workflows.agent_team import subagent_runtime as runtime

    async def _fail(*args, **kwargs):
        raise TimeoutError("recovery timed out")

    monkeypatch.setattr(runtime, "chat_with_fallback_budget", _fail)
    records = [
        _research("root.job.1", "BODY ONE"),
        _research("root.job.2", "BODY TWO"),
        _verification(),
    ]
    messages = [
        _report_block(
            "root.job.3",
            '{"verification_results":[{"check_id":"quote_fidelity","verdict":"fail"}]}',
            agent="quote_verify_verification",
            status="incomplete",
        )
    ]
    result = AgentLoopResult(
        messages=messages,
        stopped_by="wall_deadline",
        metadata={
            "final_answer_candidate": "REJECTED CANDIDATE",
            "team_wind_down": {"collected_count": 2},
        },
    )

    result = await force_final_answer(
        result,
        object(),
        1.0,
        task_description="q",
        force_recovery=True,
        prefer_collected_reports=True,
        run_recovery_llm=True,
        member_reports=records,
    )

    assert "BODY ONE" in result.final_content
    assert "BODY TWO" in result.final_content
    assert "REJECTED CANDIDATE" not in result.final_content
    assert "quote_fidelity: fail" in result.final_content
    assert result.metadata["final_answer_source"] == "collected_report_fallback"
    assert result.metadata["recovery_calls"][0]["usage_status"] == "unavailable"


def test_oversized_report_keeps_source_and_excerpt_marker() -> None:
    records = [_research("root.job.1", "A" * 200_000)]

    output = _collected_report_fallback([], records)

    assert len(output) <= _STITCH_MAX_CHARS + 2_000
    assert "root.job.1" in output
    assert "摘录" in output
    assert "完整报告见运行轨迹" in output
