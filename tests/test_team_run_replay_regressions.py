"""Replay regressions from two real web deep-read runs, without model calls.

Round 1 dispatched three extractors bound to one work item with disjoint unit
ranges; round 2 dispatched a rear-segment reader whose assigned range never
reached its execution text (it read the front half instead), a late report
that never touched the assigned range still flipped the task to resolved, and
a finished coordinator synthesis was replaced by stitched raw reports after
the recovery call timed out. Each test drives the real dispatch, board and
finalization code paths, so the production failures reproduce mechanically
rather than through log strings.
"""

import asyncio
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import tool_msg
from tests.test_agent_team_inherited_publish_directive import TASK_ID, _FakeBus, _session


@pytest.fixture
def replay_dispatch():
    """Real dispatch/board tools against a bus that keeps the member prompts."""
    from frontier_agent.components.agent_bus import AgentBus
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from frontier_agent.core.runtime import registry
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from plugins.tools.task_board import clear_board

    names = ("extract_a", "extract_b", "extract_c", "extract_d")
    bus = _FakeBus({f"{TASK_ID}::{name}": _session(name) for name in names})
    jobs: list[SimpleNamespace] = []
    bus.list_task_jobs = lambda *_: jobs
    bus.get_job_result = lambda *_args, **_kwargs: (
        f"{TASK_ID}::extract_c",
        SimpleNamespace(final_content="", metadata={}),
    )
    runtime = SimpleNamespace(
        publication_state={},
        publication_lock=asyncio.Lock(),
        verification_lock=asyncio.Lock(),
        sub_binds=(),
        original_question="",
    )
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(
        ExecutionScope(task_id=TASK_ID, metadata={SWARM_SCOPE_KEY: runtime})
    )
    yield bus, jobs
    clear_board(TASK_ID)
    reset_current_execution_scope(token)
    registry.restore(saved)


async def test_segment_ranges_reach_member_execution_text(replay_dispatch):
    """Round-1 shape: three extractors share one work item, each owning a
    disjoint unit span. Every member must see its own span and where to start
    reading, so the rear members do not restart from page one."""
    from plugins.tools.assign_task import agent_team_assign_task
    from plugins.tools.task_board import add_task

    bus, _jobs = replay_dispatch
    await add_task.func(
        [
            {"description": "抽取文档前段（unit 1–99）：结构、方法与关键表", "kind": "research"},
            {"description": "抽取文档中段（unit 100–199）：情景与算力路径", "kind": "research"},
            {"description": "抽取文档后段（unit 200–272）：竞争格局与风险", "kind": "research"},
        ]
    )
    specs = [
        {
            "agent": "extract_a",
            "prompt": "精读你负责的单元区间，逐条记录 locator",
            "unit_range": [1, 99],
            "work_item_ids": ["t1"],
        },
        {
            "agent": "extract_b",
            "prompt": "精读你负责的单元区间，逐条记录 locator",
            "unit_range": [100, 199],
            "work_item_ids": ["t2"],
        },
        {
            "agent": "extract_c",
            "prompt": "精读你负责的单元区间，逐条记录 locator",
            "unit_range": [200, 272],
            "work_item_ids": ["t3"],
        },
    ]
    reply = await agent_team_assign_task.func(tasks=specs)
    assert not reply.startswith("Error"), reply
    assert len(bus.submitted) == 3
    for spec, (_session_id, prompt, metadata) in zip(specs, bus.submitted, strict=True):
        lo, hi = spec["unit_range"]
        assert f"unit:{lo:04d}" in prompt, "member must know where to start reading"
        assert str(lo) in prompt and str(hi) in prompt, "member must see the span it owns"
        assert metadata.get("unit_range") == [lo, hi]
    assert len({prompt for _s, prompt, _m in bus.submitted}) == 3


async def test_document_paging_stamps_observed_unit_coverage():
    """Coverage positions derive from page receipts, not model claims: a
    clamped page reports its filtered end index and item count, so the job
    metadata carries absolute source positions the finalization gate can use."""
    import json

    from frontier_agent.core.loop_types import ToolResult
    from plugins.corpus.progress import CorpusCoverageObserver
    from tests.test_corpus_progress import context

    observer, ctx = CorpusCoverageObserver(), context()
    for end, count in ((10, 10), (12, 2)):
        ctx.turn += 1
        call_id = f"call-{ctx.turn}"
        payload = {
            "ok": True,
            "doc_id": "cv2:" + "1" * 64,
            "scope": "document",
            "unit_range": [150, 272],
            "total_units": 123,
            "position": {"unit_index": end, "offset": 0},
            "items": [{"unit_id": f"u{i}"} for i in range(count)],
        }
        raw = json.dumps(payload)
        ctx.tool_calls = [{"name": "corpus_fetch", "args": {"doc_id": payload["doc_id"]}}]
        await observer.on_tool_result(ctx, ToolResult("corpus_fetch", {}, raw, 0, call_id, False))
        ctx.messages.append({"role": "tool", "tool_call_id": call_id, "content": raw})
        await observer.on_turn_end(ctx)
    result = AgentLoopResult(messages=[], metadata={})
    await observer.on_loop_end(result)
    assert result.metadata["observed_unit_coverage"] == list(range(150, 162))


async def test_resolution_after_remediation_accepts_covering_evidence(replay_dispatch):
    """Completion accounting must allow remediation: once a re-dispatched
    member actually delivers the assigned span, the task resolves normally."""
    from plugins.tools.assign_task import agent_team_assign_task
    from plugins.tools.task_board import add_task, update_task

    _bus, jobs = replay_dispatch
    await add_task.func(
        [
            {
                "description": "深读文档后段（unit 150–272）：竞争格局、估值含义、风险与催化剂",
                "kind": "research",
                "done_when": "后段关键论点逐条附 doc_id 与 unit locator，标注原述与推断",
            }
        ]
    )
    for agent, span in (("extract_c", [150, 272]), ("extract_d", [150, 272])):
        reply = await agent_team_assign_task.func(
            tasks=[
                {
                    "agent": agent,
                    "prompt": "精读你负责的单元区间，逐条记录 locator",
                    "unit_range": span,
                    "work_item_ids": ["t1"],
                }
            ]
        )
        assert not reply.startswith("Error"), reply
        if agent == "extract_c":
            # Window closes before the late report; the gap is recorded, then
            # the item re-opens for a remediation dispatch, mirroring the
            # production sequence.
            reply = await update_task.func(
                updates=[
                    {
                        "id": "t1",
                        "resolution": "cancelled",
                        "notes": "研究窗口关闭时该分段任务仍在运行，未收到回传",
                        "gap": "后段未由专段覆盖",
                    }
                ]
            )
            assert not reply.startswith("Error"), reply
            reply = await update_task.func(
                updates=[
                    {
                        "id": "t1",
                        "resolution": "in_progress",
                        "notes": "窗口重新开放，派发补齐成员覆盖后段",
                    }
                ]
            )
            assert not reply.startswith("Error"), reply
    jobs.append(
        SimpleNamespace(
            job_id="job-1",
            status="completed",
            item=SimpleNamespace(metadata={"unit_range": [150, 272]}),
            result=SimpleNamespace(
                final_content="读到 unit 0001–0115；其自述 p11 末至 p15 未读。",
                metadata={"observed_unit_coverage": [1, 115]},
            ),
        )
    )
    jobs.append(
        SimpleNamespace(
            job_id="job-2",
            status="completed",
            item=SimpleNamespace(metadata={"unit_range": [150, 272]}),
            result=SimpleNamespace(
                final_content="unit 0150–0272 已逐条整理，含估值与风险清单。",
                metadata={"observed_unit_coverage": list(range(150, 273))},
            ),
        )
    )
    reply = await update_task.func(
        updates=[
            {
                "id": "t1",
                "resolution": "resolved",
                "notes": "补齐派发的成员回传覆盖 unit 150–272 全部单元",
                "evidence_refs": ["job-2"],
            }
        ]
    )
    assert not reply.startswith("Error"), reply


async def test_late_report_without_assigned_coverage_cannot_resolve(replay_dispatch):
    """Round-2 t3 replay: the rear-segment assignment owns units 150-272, the
    member returns late having read units 1-115 and declares the target half
    unread. Flipping the cancelled task to resolved without an explicit gap
    accounting must be rejected, not projected as success."""
    from plugins.tools.assign_task import agent_team_assign_task
    from plugins.tools.task_board import add_task, snapshot_tasks, update_task

    _bus, jobs = replay_dispatch
    await add_task.func(
        [
            {
                "description": "深读文档后段（unit 150–272）：竞争格局、估值含义、风险与催化剂",
                "kind": "research",
                "done_when": "后段关键论点逐条附 doc_id 与 unit locator，标注原述与推断",
            }
        ]
    )
    reply = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "extract_c",
                "prompt": "精读你负责的单元区间，逐条记录 locator",
                "unit_range": [150, 272],
                "work_item_ids": ["t1"],
            }
        ]
    )
    assert not reply.startswith("Error"), reply
    jobs.append(
        SimpleNamespace(
            job_id="job-1",
            status="completed",
            item=SimpleNamespace(metadata={"unit_range": [150, 272]}),
            result=SimpleNamespace(
                final_content="读到 unit 0001–0115；其自述 p11 末至 p15 未读（估值倍数/风险清单全文）。",
                metadata={"observed_unit_coverage": [1, 115]},
            ),
        )
    )
    reply = await update_task.func(
        updates=[
            {
                "id": "t1",
                "resolution": "cancelled",
                "notes": "研究窗口关闭时该分段任务仍在运行，未收到回传",
                "gap": "后段未由专段覆盖",
            }
        ]
    )
    assert not reply.startswith("Error"), reply
    reply = await update_task.func(
        updates=[
            {
                "id": "t1",
                "resolution": "resolved",
                "notes": "后段读者实际返回（延迟回传）：读到 unit 0001–0115，其自述 p11 末至 p15 未读",
                "evidence_refs": ["job-1"],
            }
        ]
    )
    assert reply.startswith("Error"), reply
    assert "150" in reply, "rejection must name the uncovered assigned span"
    assert snapshot_tasks(TASK_ID)[0]["resolution"] == "cancelled"


def test_late_incomplete_jobs_do_not_invalidate_finished_synthesis():
    """Round-2 root cause: the wind-down counted any late arrival as evidence.
    Only reports from jobs classified complete can substantively change the
    answer body; a failed or timed-out delivery is a status update. A partial
    run stays disclosed, but a usable draft is no longer forced through a
    doomed resynthesis."""
    from workflows.agent_team.lifecycle import TeamWindDown

    draft = "# 深度解读：示例研报\n\n情景结论：乐观情景 2028 年底在轨算力约 1 GW。"
    result = AgentLoopResult(messages=[], final_content=draft, metadata={})
    wind_down = TeamWindDown(
        status="partial",
        checkpoint="",
        collected_count=2,
        new_evidence_count=0,
        incomplete_count=2,
        queued_aborted=0,
        unresolved_count=0,
    )
    assert wind_down.requires_resynthesis is True, "partial run stays disclosed"
    assert wind_down.should_refresh_answer(result) is False
    stale_draft = AgentLoopResult(messages=[], final_content="", metadata={})
    assert wind_down.should_refresh_answer(stale_draft) is True
    substantive = TeamWindDown(
        status="partial",
        checkpoint="",
        collected_count=1,
        new_evidence_count=1,
        incomplete_count=0,
        queued_aborted=0,
        unresolved_count=0,
    )
    assert substantive.should_refresh_answer(result) is True


async def test_recovery_failure_preserves_finished_synthesis():
    """Round-2 replay: the coordinator latched a complete post-fan-in
    synthesis, wind-down then counted collected reports, and the clean-context
    recovery call timed out. The finished synthesis must survive with its
    limits recorded instead of degrading to the stitched-report fallback."""
    from workflows.agent_team.subagent_runtime import force_final_answer

    synthesis = (
        "# 深度解读：示例研报\n\n"
        "情景结论：乐观情景 2028 年底在轨算力约 1 GW，基准约 0.5 GW。\n\n"
        "## 已核验边界\n\n两项必验检查未取得判定，关键数值仍为未核验。"
    )
    member_report = (
        '<report agent="reader" job="job-3">读到 unit 0001–0115；p11 末至 p15 未读。</report>'
    )
    result = AgentLoopResult(
        messages=[tool_msg(member_report, "job-3")],
        final_content=synthesis,
        turns_used=12,
        tool_calls_count=13,
        stopped_by="final_answer",
        metadata={
            "final_answer": synthesis,
            "final_answer_confidence": 1.0,
            "team_wind_down": {"collected_count": 4, "run_status": "partial"},
        },
    )

    class TimeoutLLM:
        async def chat(self, *_args, **_kwargs):
            raise TimeoutError("logical recovery call timed out")

    await force_final_answer(
        result,
        TimeoutLLM(),
        1.0,
        task_description="深度解读这份研报",
        force_recovery=True,
        prefer_collected_reports=True,
        run_recovery_llm=True,
    )
    assert result.metadata["final_answer"] == synthesis
    assert result.final_content == synthesis
    assert "Best-effort collected results" not in result.metadata["final_answer"]
    assert result.metadata["final_answer_source"] == "existing_partial"
    assert result.metadata["final_answer_refresh_failed"] is True
