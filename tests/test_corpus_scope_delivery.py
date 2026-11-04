"""Bounded retrieval is not proof of corpus-wide absence or latestness."""

import json
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.loop_types import ToolResult
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

COVERAGE = {
    "processing": "partial",
    "availability": "unknown",
    "purity": {"scope": "bounded_candidates_not_corpus_absence"},
    "native": {"sources": 61, "chunks": 1625, "unknown_date_sources": ["undated"]},
}


async def test_corpus_search_scope_survives_member_report():
    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    await observer.on_tool_result(
        ctx,
        ToolResult(
            name="corpus_search",
            args={"query": "DeepSeek"},
            result=json.dumps({"ok": True, "coverage": COVERAGE}),
            duration_ms=1,
            tool_call_id="search",
            is_error=False,
        ),
    )
    assert ctx.metadata.get("content_acquisition"), "corpus limits must not vanish at handoff"
    observation = ctx.metadata["content_acquisition"][0]
    assert observation["coverage"]["availability"] == "unknown"


def test_report_cannot_promote_partial_search_to_global_absence():
    out = finalize_team_report(
        "全库没有更晚的模型发布。\n本次取回的研报描述了十月更新。",
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        wind_down={
            "run_status": "complete",
            "status": "complete",
            "job_outcomes": [
                {
                    "job_id": "research",
                    "status": "complete",
                    "content_acquisition": [
                        {
                            "tool": "corpus_search",
                            "source": "DeepSeek",
                            "obtained": True,
                            "status": "success",
                            "coverage": COVERAGE,
                        }
                    ],
                }
            ],
        },
    )
    assert out["answer_status"] == "partial"
    assert "全库没有更晚的模型发布。" not in out["final_answer"]
    assert "本次取回的研报描述了十月更新。" in out["final_answer"]


def test_board_gap_cannot_reintroduce_removed_corpus_claim():
    out = finalize_team_report(
        "本次取回的研报描述了十月更新。",
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        language="zh",
        tasks=[
            {
                "id": "t1",
                "description": "比较不同版本",
                "resolution": "blocked",
                "gap": "库内无早期世代文档。跨代比较仍未完成。",
            }
        ],
        wind_down={
            "job_outcomes": [
                {
                    "job_id": "research",
                    "status": "complete",
                    "content_acquisition": [
                        {"tool": "corpus_search", "obtained": True, "coverage": COVERAGE}
                    ],
                }
            ]
        },
    )
    assert "库内无早期世代文档" not in out["final_answer"]
    assert "跨代比较仍未完成" in out["final_answer"]
    assert out["answer_status"] == "partial"


@pytest.mark.parametrize(
    "text",
    [
        "全库没有更晚的发布。",
        "库内完全没有旧模型文档。",
        "资料库零覆盖。",
        "资料库里只有3篇文档。",
        "本次检索结束，全库没有更晚的发布。",
        "全库最新模型是甲。",
        "No later release exists in the entire corpus.",
    ],
)
def test_absolute_scope_requires_more_than_bounded_search(text):
    from plugins.tools._corpus_scope import corpus_scope_findings

    assert corpus_scope_findings(
        text, [{"tool": "corpus_search", "obtained": True, "coverage": COVERAGE}]
    )


@pytest.mark.parametrize(
    "text",
    [
        "本次检索未发现更晚的发布。",
        "在已取回的资料中，最新记录是十月更新。",
        "不能断言全库没有更多记录。",
        "这不代表全库没有其他材料。",
        "We cannot conclude no later release exists in the entire corpus.",
        "需求可能继续增长，这是研究员的预测。",
    ],
)
def test_scoped_observations_and_forecasts_remain_publishable(text):
    from plugins.tools._corpus_scope import corpus_scope_findings

    assert not corpus_scope_findings(
        text, [{"tool": "corpus_search", "obtained": True, "coverage": COVERAGE}]
    )


async def test_verifier_cannot_pass_absence_using_its_own_bounded_search(tmp_path):
    from plugins.tools._verification import (
        VerificationCheck,
        bind_checks,
        reset_verification_scope,
        set_verification_scope,
        validate_results,
    )
    from tests.test_agent_team_verification import make_bound, planned_items, verdict_for

    bus, spec, _ = make_bound(tmp_path)
    spec = VerificationCheck.model_validate(
        {**spec.model_dump(), "subject": {"text": "全库没有更晚的发布。"}}
    )
    checks, _ = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    token = set_verification_scope("review", {"verification_checks": checks})
    try:
        observer = ContentAcquisitionObserver()
        await observer.on_tool_result(
            SimpleNamespace(metadata={}),
            ToolResult(
                name="corpus_search",
                args={"query": "later release"},
                result=json.dumps({"ok": True, "coverage": COVERAGE}),
                duration_ms=1,
                tool_call_id="search",
                is_error=False,
            ),
        )
        with pytest.raises(ValueError, match="bounded corpus retrieval"):
            validate_results([verdict_for(checks[0])])
        assert validate_results([verdict_for(checks[0], verdict="unchecked")])
    finally:
        reset_verification_scope(token)


def test_bound_evidence_keeps_scope_and_blocks_unqualified_delivery(tmp_path):
    from frontier_agent.core.runtime import registry
    from plugins.tools._verification import (
        VerificationCheck,
        bind_checks,
        reset_verification_scope,
        set_verification_scope,
        validate_results,
    )
    from plugins.tools.finalize_answer import finalize_gate
    from tests.test_agent_team_verification import make_bound, planned_items, verdict_for

    bus, spec, _ = make_bound(tmp_path)
    observation = {"tool": "corpus_search", "obtained": True, "coverage": COVERAGE}
    bus._jobs["source"].result.metadata["content_acquisition"] = [observation]
    spec = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": "全库没有更晚的发布。"},
        }
    )
    checks, _ = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    limit = checks[0]["evidence"][0]["corpus_limits"][0]
    assert limit["coverage"]["purity"] == COVERAGE["purity"]
    assert limit["coverage"]["native"]["unknown_date_sources"]
    assert bus._jobs["source"].result.metadata["content_acquisition"] == [observation]
    token = set_verification_scope("review", {"verification_checks": checks})
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    try:
        with pytest.raises(ValueError, match="bounded corpus retrieval"):
            validate_results([verdict_for(checks[0])])
        assert "bounded corpus search" in finalize_gate("run", "全库没有更晚的发布。")
        assert finalize_gate("run", "本次检索未发现更晚的发布。") is None
    finally:
        registry.restore(saved)
        reset_verification_scope(token)
