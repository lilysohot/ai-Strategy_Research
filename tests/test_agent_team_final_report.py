from __future__ import annotations

import json

import pytest

from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import tool_msg
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.nodes.reporter import agent_team_reporter
from workflows.agent_team.subagent_runtime import force_final_answer


def publish(text, **kwargs):
    return finalize_team_report(
        text,
        source=kwargs.pop("source", "agent"),
        answer_status=kwargs.pop("answer_status", "complete"),
        stopped_by=kwargs.pop("stopped_by", "final_answer"),
        **kwargs,
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        '<report agent="worker">RAW_MEMBER_RESULT</report>',
        '<tool_call>{"name":"bash"}</tool_call>',
        "<function=bash><parameter=command>ls",
        "<think>unfinished reasoning",
        "<ANSWER_NOT_FOUND>",
        "Traceback (most recent call last):\nRAW_MEMBER_RESULT",
        '{"name":"bash","arguments":{"command":"ls"}}',
        '```json\n{"tool_calls":[{"function":{"name":"bash"}}]}\n```',
    ],
)
def test_internal_or_empty_output_is_never_published(text):
    out = publish(text, question="核对订单", stopped_by="llm_error")
    assert out["final_answer_source"] == "deterministic_fallback"
    assert "系统根据执行记录" in out["final_answer"]
    assert "RAW_MEMBER_RESULT" not in out["final_answer"]
    assert "<tool_call>" not in out["final_answer"]
    assert out["report_contract"]["kind"] == "system_status"
    assert out["answer_status"] == "not_found"
    json.dumps(out, ensure_ascii=False)


def test_complete_text_is_unchanged_and_board_claims_are_not_verification():
    text = 'Requested JSON: {"value": 42}'
    out = publish(text, tasks=[{"id": "t1", "description": "Read", "resolution": "resolved"}])
    assert out["final_answer"] == text
    assert out["report_contract"]["kind"] == "complete"
    assert out["report_contract"]["task_board_basis"] == "coordinator_declared"
    assert out["report_contract"]["artifact_verification"] == "not_assessed"


def test_resolved_board_retains_declared_evidence_gap_and_prefixes_partial_answer():
    draft = "按当前已读来源，A 的成本较低；B 的现价未确认。"
    out = publish(
        draft,
        question="比较成本",
        tasks=[
            {
                "id": "t1",
                "description": "比较现价",
                "resolution": "resolved",
                "gap": "B 的官方现价未确认",
                "owners": ["pricing"],
            }
        ],
    )
    assert out["answer_status"] == "partial"
    assert any(
        g["code"] == "task_evidence_gap" and g["task_id"] == "t1"
        for g in out["report_contract"]["gaps"]
    )
    assert out["final_answer"].index("部分完成") < out["final_answer"].index(draft)
    assert "B 的官方现价未确认" in out["final_answer"]


def test_task_resolution_is_separate_from_observed_member_execution():
    draft = "Available evidence supports a provisional comparison."
    out = publish(
        draft,
        tasks=[
            {
                "id": "t1",
                "description": "pricing",
                "resolution": "resolved",
                "owners": ["pricing"],
            }
        ],
        wind_down={
            "job_outcomes": [
                {
                    "job_id": "job-1",
                    "agent": "pricing",
                    "required": True,
                    "status": "incomplete",
                    "reason": "wall_deadline",
                    "source": "tool_observations",
                }
            ]
        },
    )
    task = out["report_contract"]["task_board"][0]
    assert task["resolution"] == "resolved"  # Retain the coordinator's declaration.
    assert task["execution_status"] == "incomplete"
    assert task["execution_job_ids"] == ["job-1"]
    assert task["verification_status"] == "not_assessed"
    assert out["answer_status"] == "partial"
    assert out["final_answer"].index("Partial result") < out["final_answer"].index(draft)


def test_blanket_verification_claim_is_withheld_when_no_checks_were_registered():
    out = publish("以上全部数字均已核对。", question="总结这份研报")

    assert out["report_contract"]["kind"] == "system_status"
    assert out["answer_status"] == "not_found"
    assert "以上全部数字均已核对" not in out["final_answer"]
    assert {gap["code"] for gap in out["report_contract"]["gaps"]} >= {
        "unsupported_verification_claim",
        "synthesis_unavailable",
    }


@pytest.mark.parametrize(
    "claim",
    [
        "全文已验证。",
        "整份研报已经完成核验。",
        "The entire document has been verified.",
    ],
)
def test_whole_document_verification_claims_require_scoped_language(claim):
    out = publish(claim, question="总结这份研报")

    assert out["report_contract"]["kind"] == "system_status"
    assert claim not in out["final_answer"]


def test_resolved_verification_task_without_bound_check_remains_a_report_gap():
    out = publish(
        "已形成研报摘要。",
        question="总结这份研报",
        tasks=[
            {
                "id": "t3",
                "description": "核验所有提炼观点",
                "resolution": "resolved",
                "verification_required": True,
            }
        ],
    )

    assert out["answer_status"] == "partial"
    assert out["report_contract"]["kind"] == "partial"
    assert any(
        gap
        == {
            "code": "task_verification_incomplete",
            "task_id": "t3",
            "status": "not_registered",
        }
        for gap in out["report_contract"]["gaps"]
    )


def test_planned_check_identity_cannot_be_satisfied_by_an_unrelated_check():
    out = publish(
        "已形成研报摘要。",
        question="总结这份研报",
        tasks=[
            {
                "id": "t3",
                "description": "核验关键数字",
                "resolution": "resolved",
                "verification_required": True,
                "verification_requirements": [
                    {
                        "check_id": "expected.amount",
                        "criterion": "复算金额",
                    }
                ],
            }
        ],
        wind_down={
            "job_outcomes": [
                {
                    "job_id": "verify.1",
                    "required": True,
                    "status": "complete",
                    "verification_checks": [
                        {
                            "check_id": "other.check",
                            "work_item_id": "t3",
                            "criterion": "检查别的内容",
                            "binding_id": "b" * 64,
                            "required": True,
                            "replaces_job_id": "",
                            "revision_reason": "",
                            "subject": {
                                "job_id": "source.1",
                                "ref": "",
                                "sha256": "s",
                                "key": "source.1",
                            },
                            "evidence": [
                                {"job_id": "source.2", "ref": "", "sha256": "e", "key": "source.2"}
                            ],
                        }
                    ],
                    "verification_events": [
                        {
                            "check_id": "other.check",
                            "binding_id": "b" * 64,
                            "verdict": "pass",
                            "job_id": "verify.1",
                        }
                    ],
                }
            ]
        },
    )

    gap = next(gap for gap in out["report_contract"]["gaps"] if gap.get("task_id") == "t3")
    assert gap["status"] == "not_registered"
    assert gap["missing_check_ids"] == ["expected.amount"]


def test_unresolved_board_prevents_complete_even_when_fan_in_is_complete():
    out = publish(
        "当前净额为 803。",
        question="核对订单",
        wind_down={"status": "complete"},
        tasks=[
            {"id": "t1", "description": "订单匹配", "resolution": "resolved"},
            {"id": "t2", "description": "重复退款核验", "resolution": "in_progress"},
            {"id": "t3", "description": "已撤回的探索", "resolution": "cancelled"},
        ],
    )
    assert out["answer_status"] == "partial"
    assert "重复退款核验" in out["final_answer"]
    assert "已撤回的探索" not in out["final_answer"]
    assert out["report_contract"]["gaps"] == [
        {"code": "task_unresolved", "task_id": "t2", "description": "重复退款核验"},
    ]


async def test_failed_rescue_keeps_evidence_internal_and_publishes_execution_facts(monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable; diagnostic details")

    monkeypatch.setattr("workflows.agent_team.subagent_runtime.chat_with_fallback_budget", fail)
    raw = '<report agent="auditor">RAW: unverified total 803</report>'
    result = AgentLoopResult(messages=[tool_msg(raw, "call-1")], stopped_by="llm_error")
    await force_final_answer(result, object(), 1, task_description="核对订单")
    out = publish(
        result.final_content,
        source=result.metadata["final_answer_source"],
        stopped_by=result.stopped_by,
        question="核对订单",
        wind_down={
            "status": "partial",
            "collected_count": 1,
            "incomplete_count": 0,
            "queued_aborted": 2,
            "unresolved_count": 1,
        },
    )
    assert raw in result.messages[0]["content"]
    assert "RAW:" not in out["final_answer"]
    assert "provider unavailable" not in out["final_answer"]
    assert "收尾阶段回收报告: 1" in out["final_answer"]
    assert "取消排队任务: 2" in out["final_answer"]
    assert "仍未回收任务: 1" in out["final_answer"]
    assert "不是主 Agent 的综合结论" in out["final_answer"]


async def test_empty_coordinator_failure_does_not_publish_a_recovery_plan(monkeypatch):
    """Replay the empty result in Web Run 0fc2dc1e before its recovery call."""
    from types import SimpleNamespace

    calls = []
    plan = "I’ll verify the input file is present, then decompose the work."

    async def recover(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(content=plan, reasoning_content="")

    monkeypatch.setattr("workflows.agent_team.subagent_runtime.chat_with_fallback_budget", recover)
    result = AgentLoopResult(messages=[], stopped_by="llm_error")
    await force_final_answer(
        result,
        object(),
        120,
        task_description="完整读取研报并核验关键事实",
    )
    out = publish(
        result.final_content,
        source=result.metadata["final_answer_source"],
        stopped_by=result.stopped_by,
        question="完整读取研报并核验关键事实",
    )

    assert calls == []
    assert out["report_contract"]["kind"] == "system_status"
    assert out["answer_status"] == "not_found"
    assert plan not in out["final_answer"]


def test_explicit_language_wins_and_board_labels_are_rendered_as_text():
    out = publish(
        "",
        language="Simplified Chinese",
        question="audit orders",
        tasks=[
            {
                "id": "t1",
                "description": "<img src=x> [click](https://example.com)",
                "resolution": "open",
            },
        ],
    )
    assert "当前可交付结果" in out["final_answer"]
    assert "<img" not in out["final_answer"]
    assert "[click](https://" not in out["final_answer"]
    assert out["report_contract"]["task_board"][0]["description"].startswith("<img")


@pytest.mark.parametrize("mode", ["error", "empty", "protocol", "success"])
async def test_reporter_failure_preserves_safe_baseline_and_success_preserves_gaps(
    monkeypatch, mode
):
    baseline = publish(
        "",
        question="核对订单",
        tasks=[
            {"id": "t1", "description": "重复退款核验", "resolution": "open"},
        ],
    )
    raw = '<report agent="auditor">INTERNAL_EVIDENCE</report>'
    state = {
        **baseline,
        "original_question": "核对订单",
        "report_handoff_context": raw,
        "metadata": {},
        "team_completeness": "partial",
    }

    async def fake_report(received, ctx):
        assert received["report_handoff_context"] == raw
        if mode == "error":
            raise RuntimeError("offline")
        return {"empty": "", "protocol": raw, "success": "已有订单匹配结果。"}[mode]

    monkeypatch.setattr(
        "workflows.agent_team.nodes.fast_reporter_v1._run_fast_reporter", fake_report
    )
    state.update(await agent_team_reporter(state, object()))
    assert "<report" not in state["final_answer"]
    assert "INTERNAL_EVIDENCE" not in state["final_answer"]
    assert "重复退款核验" in state["final_answer"]
    if mode == "success":
        assert state["final_answer_source"] == "reporter_llm"
        assert state["answer_status"] == "partial"
        assert state["report_contract"]["kind"] == "partial"
    else:
        assert state["final_answer"] == baseline["final_answer"]
        assert state["report_contract"]["kind"] == "system_status"


@pytest.mark.parametrize(
    "draft",
    [
        "已获充分交叉验证。",
        "final_verifier 虽因时限未给出书面结论，但其工具观测与草稿吻合，草稿已获充分交叉验证。",
        "The reviewer did not finish, but all findings are verified.",
    ],
)
async def test_collected_deadline_report_cannot_be_erased_by_resolved_board(monkeypatch, draft):
    from frontier_agent.components.agent_bus import AgentBus
    from workflows.agent_team.lifecycle import wind_down_team

    async def stopped_member(**kwargs):
        return AgentLoopResult(
            messages=[],
            final_content="RAW_OBSERVATIONS_ONLY",
            stopped_by="wall_deadline",
            metadata={"final_answer_source": "tool_observations", "stopped_by": "wall_deadline"},
        )

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        stopped_member,
    )
    bus = AgentBus()
    session = await bus.create_session(
        task_id="review-run",
        name="final_verifier",
        role_id="researcher",
        system_prompt="Verify the source",
        tools_override=[],
        llm_override=object(),
    )
    job = await bus.submit_task_to_session(session, "Verify all figures")
    try:
        assert await bus.wait_any_session("review-run", timeout=1) is not None
        wind = await wind_down_team(bus=bus, task_id="review-run", wait_s=0)
        assert wind.collected_count == 0
        out = publish(
            draft,
            question="这份研报说了什么",
            wind_down=wind.as_dict(),
            tasks=[{"id": "t3", "description": "终审核验", "resolution": "resolved"}],
        )
        assert out["answer_status"] != "complete"
        assert any(gap.get("job_id") == job for gap in out["report_contract"]["gaps"])
        assert "已获充分交叉验证" not in out["final_answer"]
        assert "RAW_OBSERVATIONS_ONLY" not in out["final_answer"]
        assert out["report_contract"]["kind"] == "system_status"
    finally:
        await bus.cleanup_task("review-run")


@pytest.mark.parametrize("early_collection", [False, True])
@pytest.mark.parametrize("required", [False, True])
async def test_optional_failure_is_audited_without_becoming_required(
    monkeypatch,
    early_collection,
    required,
):
    from frontier_agent.components.agent_bus import AgentBus
    from workflows.agent_team.lifecycle import wind_down_team

    async def stopped(**kwargs):
        return AgentLoopResult(
            messages=[],
            final_content="partial",
            stopped_by="wall_deadline",
            metadata={"stopped_by": "wall_deadline"},
        )

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", stopped)
    bus = AgentBus()
    session = await bus.create_session(
        task_id="optional",
        name="explorer",
        role_id="researcher",
        system_prompt="Explore",
        tools_override=[],
        llm_override=object(),
    )
    job = await bus.submit_task_to_session(
        session,
        "Explore background",
        task_metadata={"required_for_completion": required},
    )
    try:
        # Await execution, without consuming its delivery queue.
        await bus._jobs[job].task
        if early_collection:
            assert await bus.wait_any_session("optional", timeout=1) is not None
        wind = await wind_down_team(bus=bus, task_id="optional", wait_s=0)
        assert wind.run_status == ("partial" if required else "complete")
        out = publish("The source states a value of 42.", wind_down=wind.as_dict())
        assert out["answer_status"] == ("partial" if required else "complete")
        assert out["report_contract"]["job_outcomes"][0]["required"] is required
        assert out["report_contract"]["verification"] == "not_assessed"
    finally:
        await bus.cleanup_task("optional")


def incomplete_wind():
    return {
        "status": "complete",
        "run_status": "partial",
        "job_outcomes": [
            {
                "job_id": "run.job.3",
                "agent": "reviewer",
                "required": True,
                "status": "incomplete",
                "reason": "wall_deadline",
            }
        ],
    }


@pytest.mark.parametrize(
    "text",
    [
        "已完成前八项核验，后两项尚未检查。",
        "Rows 1–8 are fully verified. Rows 9–10 remain unchecked.",
        "Not all findings are verified.",
        "全部核验任务失败，当前仅有原始观测。",
    ],
)
def test_scoped_or_negative_verification_statements_keep_useful_content(text):
    out = publish(text, wind_down=incomplete_wind())
    assert text in out["final_answer"]
    assert out["final_answer"].startswith("**Partial result:")
    assert out["answer_status"] == "partial"
    assert out["report_contract"]["source"] == "model"


async def test_reporter_cannot_erase_previously_collected_job_gap(monkeypatch):
    baseline = publish("已有部分结果。", question="总结", wind_down=incomplete_wind())

    async def report(*args):
        return "已获充分交叉验证。"

    monkeypatch.setattr("workflows.agent_team.nodes.fast_reporter_v1._run_fast_reporter", report)
    out = await agent_team_reporter(
        {
            **baseline,
            "original_question": "总结",
            "metadata": {},
            "team_completeness": "partial",
        },
        object(),
    )
    assert out["report_contract"]["kind"] == "system_status"
    assert "已获充分交叉验证" not in out["final_answer"]
    assert any(gap.get("job_id") == "run.job.3" for gap in out["report_contract"]["gaps"])


async def test_reporter_cannot_drop_explicit_inference_labels(monkeypatch):
    baseline = publish("[推断] GPU 租赁价格可能继续承压。", question="总结")

    async def report(*args):
        return "GPU 租赁价格将继续承压。"

    monkeypatch.setattr("workflows.agent_team.nodes.fast_reporter_v1._run_fast_reporter", report)
    out = await agent_team_reporter(
        {
            **baseline,
            "original_question": "总结",
            "metadata": {},
            "team_completeness": "complete",
            "report_handoff_context": baseline["final_answer"],
        },
        object(),
    )

    assert out == {}
