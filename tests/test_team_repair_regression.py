"""Minimized failure chain from Web run 6d4a2c7200124b2b9c91c08960133cae."""

import json

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.runtime.loop.tool_call_parser import MultiFormatToolCallParser
from plugins.tools._corpus_scope import corpus_scope_findings
from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    reset_verification_scope,
    set_verification_scope,
    unresolved_publication_claims,
    validate_results,
)
from tests.test_agent_team_verification import add_job, make_bound, planned_items, verdict_for
from tests.test_corpus_manifest_tool import run_env as _run_env
from tests.test_corpus_scope_delivery import COVERAGE
from tests.test_team_atomic_delivery import delivery_run as _delivery_run

run_env = _run_env
delivery_run = _delivery_run


def dsml(arguments):
    params = []
    for name, value in arguments.items():
        is_string = isinstance(value, str)
        body = value if is_string else json.dumps(value, ensure_ascii=False)
        params.append(
            f'<｜｜DSML｜｜ parameter name="{name}" string="{str(is_string).lower()}">'
            f"{body}</｜｜DSML｜｜ parameter>"
        )
    return (
        '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="submit_report">\n'
        + "\n".join(params)
        + "\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>"
    )


def bounded_source(tmp_path):
    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata["content_acquisition"] = [
        {"tool": "corpus_search", "obtained": True, "coverage": COVERAGE},
    ]
    return bus, spec


def bind(bus, spec, tmp_path):
    return bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )


def test_dsml_recovers_typed_report_call():
    args = {
        "content": "核验报告",
        "confidence": 0.85,
        "finish": False,
        "verification_results": [{"verdict": "unchecked", "evidence_keys": ["source"]}],
    }
    parsed = MultiFormatToolCallParser().parse(LLMResponse(content=dsml(args)), {"submit_report"})
    assert len(parsed) == 1
    assert parsed[0]["name"] == "submit_report"
    assert parsed[0]["args"] == args


def test_recheck_rejects_remaining_scope_defect_before_dispatch(tmp_path):
    bus, spec = bounded_source(tmp_path)
    first, _ = bind(bus, spec, tmp_path)
    add_job(bus, "first", first, verdicts=["fail"])
    revision = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": "作者已修正。资料库中没有任何适配公告。"},
            "replaces_job_id": "first",
            "revision_kind": "subject",
            "revision_reason": "修正作者",
        }
    )
    before = len(bus.list_task_jobs("run"))
    with pytest.raises(ValueError, match="资料库中没有"):
        bind(bus, revision, tmp_path)
    assert len(bus.list_task_jobs("run")) == before


def test_focused_recheck_keeps_originals_without_full_research_report(tmp_path):
    bus, spec = bounded_source(tmp_path)
    report = "UNRELATED_REPORT_PARAGRAPH " * 2500
    source = bus._jobs["source"].result
    source.final_content = report
    original = (
        "Atlas release: date unknown; this is an analyst estimate, not a vendor announcement."
    )
    source.metadata["corpus_evidence"] = [
        {"doc_id": "cv2:" + "a" * 64, "locator": "body:0000", "text": original}
    ]
    first, _ = bind(bus, spec, tmp_path)
    add_job(bus, "first", first, verdicts=["fail"])
    revision = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": "Atlas: date unknown; analyst estimate only."},
            "replaces_job_id": "first",
            "revision_kind": "subject",
            "revision_reason": "Restore scope",
        }
    )
    checks, prompt = bind(bus, revision, tmp_path)
    assert len(prompt) < 16000
    assert original in prompt
    assert "omitted" in prompt.lower()
    assert source.final_content == report
    assert checks[0]["evidence"] == first[0]["evidence"]


@pytest.mark.parametrize("subject_is_report", [False, True])
def test_context_projection_never_hides_only_evidence_or_bound_subject(tmp_path, subject_is_report):
    bus, spec = bounded_source(tmp_path)
    body = "Claim and its material condition.\n\n" * 1000 + "CONDITION_AT_END"
    source = bus._jobs["source"].result
    source.final_content = body
    if subject_is_report:
        source.metadata["corpus_evidence"] = [
            {
                "doc_id": "cv2:" + "a" * 64,
                "locator": "body:0000",
                "text": "Source excerpt",
            }
        ]
        spec = VerificationCheck.model_validate(
            {**spec.model_dump(), "subject": {"job_id": "source"}}
        )
    _, prompt = bind(bus, spec, tmp_path)
    assert body in prompt


@pytest.mark.parametrize(
    "text",
    [
        "按资料库记载，DeepSeek 当前最新模型是 Atlas。",
        "资料库记载的最新 DeepSeek 模型是 Atlas。",
    ],
)
def test_paraphrased_latestness_does_not_evade_scope_gate(text):
    assert corpus_scope_findings(
        text,
        [
            {"tool": "corpus_search", "obtained": True, "coverage": COVERAGE},
        ],
    )


async def test_repair_chain_keeps_guard_after_dsml_recovery(tmp_path):
    from plugins.tools.submit_report import submit_report

    bus, spec = bounded_source(tmp_path)
    bad = VerificationCheck.model_validate(
        {**spec.model_dump(), "subject": {"text": "资料库中没有任何适配公告。"}}
    )
    checks, _ = bind(bus, bad, tmp_path)
    metadata = {"verification_checks": checks}
    token = set_verification_scope("first", metadata)
    try:
        args = {
            "content": "Scope: exact claim. Finding: unsupported absence.",
            "verification_results": [verdict_for(checks[0])],
        }
        calls = MultiFormatToolCallParser().parse(
            LLMResponse(content=dsml(args)), {"submit_report"}
        )
        assert len(calls) == 1
        rejected = await submit_report.func(**calls[0]["args"])
        assert rejected.is_error
        assert "bounded corpus retrieval" in rejected.result
        assert metadata["verification_events"] == []
        accepted = await submit_report.func(
            content="Scope: exact claim. Finding: fail.",
            verification_results=[verdict_for(checks[0], verdict="fail")],
        )
        assert json.loads(accepted)["verification_results"][0]["verdict"] == "fail"
        assert len(metadata["verification_events"]) == 1
    finally:
        reset_verification_scope(token)
    _finish_repair_chain(bus, bad, checks, tmp_path)


def _finish_repair_chain(bus, bad, checks, tmp_path):
    add_job(bus, "first", checks, verdicts=["fail"])
    good = VerificationCheck.model_validate(
        {
            **bad.model_dump(),
            "subject": {"text": "本次检索未发现适配公告，不能据此断言不存在。"},
            "replaces_job_id": "first",
            "revision_kind": "subject",
            "revision_reason": "Bounded scope",
        }
    )
    revised, _ = bind(bus, good, tmp_path)
    assert revised[0]["binding_id"] != checks[0]["binding_id"]
    token = set_verification_scope("second", {"verification_checks": revised})
    try:
        with pytest.raises(ValueError, match="binding_id"):
            validate_results([verdict_for(checks[0])])
        assert validate_results([verdict_for(revised[0])])[0]["verdict"] == "pass"
    finally:
        reset_verification_scope(token)


async def test_delivery_returns_anchor_and_scope_defects_together(run_env, delivery_run):
    from plugins.corpus.ledger import get_run_ledger, load_manifest_files
    from plugins.tools.task_board import snapshot_tasks
    from tests.test_corpus_manifest_tool import _conclusion, _fetch_body
    from workflows.agent_team.delivery import deliver_answer

    bus, _ = delivery_run
    add_job(bus, "source", [])
    bus._jobs["source"].result.metadata["content_acquisition"] = [
        {"tool": "corpus_search", "obtained": True, "coverage": COVERAGE},
    ]
    ledger = get_run_ledger()
    ledger.record_fetch_result(_fetch_body())
    ledger.finalize([{"role": "tool", "content": _fetch_body()}])
    board = snapshot_tasks("run")
    with pytest.raises(ValueError) as caught:
        await deliver_answer.func(
            content="资料库记载的最新模型是 Atlas。",
            updates=[],
            corpus_conclusions=[_conclusion(report_quote="OLD_DRAFT")],
        )
    assert "report_quote" in str(caught.value)
    assert "corpus_scope_overstatement" in str(caught.value)
    assert snapshot_tasks("run") == board
    assert not load_manifest_files()


async def test_failed_publication_claim_cannot_survive_as_an_equivalent_absolute_claim(
    delivery_run,
):
    checks = [
        {
            "check_id": "lead_claim",
            "work_item_id": "t4",
            "criterion": "不得把局部领先表述为全球断层领先",
            "required": True,
            "factual_scope": True,
            "publication_excerpt": True,
            "verdict": "fail",
            "subject": {
                "text": "应用侧渗透率属全球最高的一档。",
                "sha256": "a" * 64,
            },
            "result": {"unresolved_issues": ["应用侧渗透率全球最高的一档缺少跨国同期对照数据。"]},
        }
    ]
    assert unresolved_publication_claims(
        checks,
        "中国AI短剧在应用侧渗透的绝对规模是全球唯一的。",
        excluded_work_items={"t4"},
    )
    assert not unresolved_publication_claims(
        checks,
        "本次没有取得跨国同期对照，不能判断中国AI短剧的全球渗透率最高。",
        excluded_work_items={"t4"},
    )
    assert not unresolved_publication_claims(
        checks,
        "核验结论：应用侧渗透率全球最高的说法未通过。文生视频榜第一为模型A。",
        excluded_work_items={"t4"},
    )

    bus, _ = delivery_run
    from tests.test_team_atomic_delivery import prepare
    from workflows.agent_team.delivery import deliver_answer

    await prepare(bus, "fail")
    check = bus._jobs["j1"].item.metadata["verification_checks"][0]
    check.update({**checks[0], "work_item_id": "t1"})
    check["binding_id"] = "b" * 64
    event = bus._jobs["j1"].item.metadata["verification_events"][0]
    event.update(
        {
            "check_id": check["check_id"],
            "binding_id": check["binding_id"],
            "subject_sha256": check["subject"]["sha256"],
            "unresolved_issues": check["result"]["unresolved_issues"],
        }
    )
    from plugins.tools._verification import project_bus_checks

    projected = project_bus_checks(bus, "run")
    assert projected["checks"][0]["verdict"] == "fail", projected
    update = [
        {
            "id": "t1",
            "resolution": "blocked",
            "notes": "跨国对照不足",
            "gap": "不能判断全球最高",
        }
    ]
    with pytest.raises(ValueError, match="failed_publication_claim_retained"):
        await deliver_answer.func(
            content="中国AI短剧在应用侧渗透的绝对规模是全球唯一的。",
            updates=update,
        )
    await deliver_answer.func(
        content="本次没有取得跨国同期对照，不能判断中国AI短剧的全球渗透率最高。",
        updates=update,
    )
