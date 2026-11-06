"""Regression shapes from run 384f: identity, bounded handoff and bad receipts."""

import json

from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from plugins.corpus.ledger import _merge_manifests, load_manifest_files
from plugins.tools._verification import bind_checks
from plugins.tools.corpus_manifest import corpus_submit_manifest
from tests.test_agent_team_verification import make_bound, planned_items
from tests.test_corpus_manifest_tool import _conclusion
from tests.test_corpus_manifest_tool import run_env as _run_env
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_corpus_handoff import DOC

run_env = _run_env
delivery_run = _delivery_run


async def test_team_members_do_not_replace_each_others_manifests(run_env):
    for job, ids in [("job.1", ["model"]), ("job.2", ["old"]), ("job.2", ["impact"])]:
        token = set_current_execution_scope(
            ExecutionScope(
                task_id="team",
                role_id="agent_team_sub",
                metadata={"agent_job_id": job},
            )
        )
        try:
            out = json.loads(
                await corpus_submit_manifest.func(
                    conclusions=[_conclusion(id=key) for key in ids],
                )
            )
            assert out["ok"]
        finally:
            reset_current_execution_scope(token)
    merged = _merge_manifests(load_manifest_files())
    assert {c["id"].split("/")[-1] for c in merged["conclusions"]} == {"model", "impact"}


async def test_bad_receipt_identifies_exact_field_without_writing_partial_manifest(run_env):
    out = json.loads(
        await corpus_submit_manifest.func(
            conclusions=[
                _conclusion(id="good"),
                _conclusion(
                    id="cost", evidence=[{"evidence_ref": "ce:25ce5803bf1d1b15033ce2f2aada5dc"}]
                ),
            ]
        )
    )
    assert not out["ok"]
    assert "conclusions[1].evidence[0].evidence_ref" in " ".join(out["errors"])
    assert "cost" in " ".join(out["errors"])
    assert not load_manifest_files()


def test_current_claims_keep_late_evidence_despite_shortened_report_refs(tmp_path):
    bus, spec, _ = make_bound(tmp_path)
    records = [
        {
            "doc_id": DOC,
            "locator": f"eref:{'a' * 64}:{i}",
            "text": f"Unrelated section {i}. " + "Noise " * 400,
        }
        for i in range(90)
    ]
    needed = [
        "新的 H100 长期协议报价为 2.90 美元，六个月前为 2.45 美元。",
        "公司预计前五大云厂 2026 年 CAPEX 将接近 8000 亿美元。",
        "我们的渠道调研表明，同等规模蒸馏实验成本是上半年的 10 到 50 倍。",
    ]
    needed = [text + "\n完整上下文和适用条件。" * 120 for text in needed]
    records.extend(
        {"doc_id": DOC, "locator": f"eref:{'b' * 64}:{i}", "text": text}
        for i, text in enumerate(needed)
    )
    bus._jobs["source"].result.metadata["corpus_evidence"] = records
    spec = type(spec).model_validate(
        {
            **spec.model_dump(),
            "subject": {
                "text": "H100 新增长期协议报价 2.90 美元；云厂 CAPEX 8000 亿美元；"
                "蒸馏实验成本 10 到 50 倍。（cv2:aaaa…，p.6）"
            },
        }
    )
    _, prompt = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    assert all(text in prompt for text in needed)
    assert len(prompt) < 42000


async def test_explicit_upsert_retains_rows_and_replace_can_remove_them(run_env):
    schema = corpus_submit_manifest.to_openai_schema()["function"]["parameters"]
    assert schema["properties"]["submission_mode"]["enum"] == ["replace", "upsert"]
    token = set_current_execution_scope(ExecutionScope(task_id="team", role_id="research"))
    try:
        await corpus_submit_manifest.func(conclusions=[_conclusion(id="model")])
        out = json.loads(
            await corpus_submit_manifest.func(
                conclusions=[_conclusion(id="impact")],
                submission_mode="upsert",
            )
        )
        assert set(out["active_conclusion_ids"]) == {"model", "impact"}
        assert len(_merge_manifests(load_manifest_files())["conclusions"]) == 2
        await corpus_submit_manifest.func(
            conclusions=[_conclusion(id="impact")], submission_mode="replace"
        )
        assert [c["id"] for c in _merge_manifests(load_manifest_files())["conclusions"]] == [
            "impact"
        ]
    finally:
        reset_current_execution_scope(token)


async def test_final_delivery_binds_current_prose_and_detects_later_edits(run_env, delivery_run):
    from plugins.corpus.ledger import get_run_ledger, verify_and_record
    from tests.test_corpus_manifest_tool import TEXT, _fetch_body
    from workflows.agent_team.delivery import deliver_answer

    ledger = get_run_ledger()
    ledger.record_fetch_result(_fetch_body())
    ledger.finalize([{"role": "tool", "content": _fetch_body()}])
    await corpus_submit_manifest.func(conclusions=[_conclusion(report_quote="OLD_DRAFT")])
    content = "根据报告，" + TEXT
    await deliver_answer.func(
        content=content, updates=[], corpus_conclusions=[_conclusion(report_quote=TEXT)]
    )
    checked = verify_and_record(
        ledger, final_text="部分完成。\n" + content, resolver=lambda *_: TEXT
    )
    assert checked["status"] == "verified", checked
    assert len(checked["conclusions"]) == 1
    changed = verify_and_record(
        ledger, final_text=content.replace("1,234", "9,999"), resolver=lambda *_: TEXT
    )
    assert changed["status"] != "verified"


async def test_final_delivery_rejects_old_anchor_before_acceptance(run_env, delivery_run):
    import pytest

    from workflows.agent_team.delivery import deliver_answer

    with pytest.raises(ValueError, match="report_quote"):
        await deliver_answer.func(
            content="This is the revised answer.",
            updates=[],
            corpus_conclusions=[_conclusion(report_quote="OLD_DRAFT")],
        )
    assert not load_manifest_files()


async def test_real_bus_loops_stamp_distinct_manifest_owners(run_env):
    import asyncio

    from frontier_agent.components.agent_bus import AgentBus
    from frontier_agent.core.llm import LLMResponse

    class Client:
        model = "scripted"

        async def chat(self, messages, **kwargs):
            return LLMResponse(content="", tool_calls=[{
                "id": "manifest", "type": "function", "function": {
                    "name": "corpus_submit_manifest",
                    "arguments": json.dumps({"conclusions": [_conclusion()]}),
                },
            }], finish_reason="tool_calls")

    bus = AgentBus()
    try:
        for name in ("model", "impact"):
            session = await bus.create_session(task_id="team", name=name, role_id="agent_team_sub",
                                               system_prompt="Research", tools_override=[corpus_submit_manifest],
                                               llm_override=Client())
            await bus.submit_task_to_session(session, "Research", max_turns=1)
        await asyncio.gather(*(job.task for job in bus.list_task_jobs("team")))
        files = load_manifest_files()
        assert len(files) == 2
        assert len({payload["owner_role"] for _, payload in files}) == 2
        assert len(_merge_manifests(files)["conclusions"]) == 2
    finally:
        await bus.cleanup_task("team")


async def test_missing_final_manifest_is_actionable_and_empty_claims_stay_draft(run_env, delivery_run):
    import pytest

    from plugins.corpus.ledger import get_run_ledger, verify_and_record
    from tests.test_corpus_manifest_tool import _fetch_body
    from workflows.agent_team.delivery import deliver_answer

    ledger = get_run_ledger()
    ledger.record_fetch_result(_fetch_body())
    with pytest.raises(ValueError, match="corpus_conclusions"):
        await deliver_answer.func(content="Unable to establish a supported conclusion.", updates=[])
    assert not load_manifest_files()
    content = "Unable to establish a supported conclusion."
    await deliver_answer.func(content=content, updates=[], corpus_conclusions=[])
    assert verify_and_record(ledger, final_text=content)["status"] == "draft"


def test_citation_index_exposes_full_ids_without_pretending_previews_are_complete():
    from plugins.tools._corpus_handoff import render_corpus_citation_index

    ref = "eref:" + "b" * 64 + ":0"
    text = "H100 new contracts 2.90 USD. " + "Condition " * 300
    result = render_corpus_citation_index({"research": [
        {"doc_id": DOC, "locator": ref, "text": text},
    ]}, focus_text="H100 2.90")
    assert ref in result
    assert '"preview_complete": false' in result
    assert text not in result
    assert len(result) < 12500


async def test_final_manifest_preserves_file_checks_but_not_superseded_file_drafts(
    run_env, delivery_run, monkeypatch,
):
    from plugins.corpus.ledger import get_run_ledger, verify_and_record
    from tests.test_corpus_manifest_tool import TEXT, _fetch_body
    from workflows.agent_team.delivery import deliver_answer

    outputs = run_env / "outputs"
    outputs.mkdir()
    report = outputs / "report.md"
    report.write_text(TEXT)
    monkeypatch.setenv("FRONTIER_AGENT_HOST_OUTPUTS_DIR", str(outputs))
    ledger = get_run_ledger()
    ledger.record_fetch_result(_fetch_body())
    ledger.finalize([{"role": "tool", "content": _fetch_body()}])
    await corpus_submit_manifest.func(conclusions=[_conclusion(report_quote=TEXT)],
                                      report_path="/outputs/report.md")
    await deliver_answer.func(content=TEXT, updates=[],
                              corpus_conclusions=[_conclusion(report_quote=TEXT)])
    def check():
        return verify_and_record(ledger, final_text=TEXT, resolver=lambda *_: TEXT)
    assert len(check()["conclusions"]) == 2
    report.write_text("Edited file")
    assert check()["status"] == "partial", "final prose must not hide an edited attachment"
    await corpus_submit_manifest.func(conclusions=[_conclusion(report_quote="NEW_DRAFT")])
    assert check()["status"] == "verified", "retired file draft was resurrected by final selection"
    assert len(check()["conclusions"]) == 1
