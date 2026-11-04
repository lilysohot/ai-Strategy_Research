"""Search evidence must survive prose handoff without recreating its locator."""

import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import AgentLoopResult, ToolResult
from plugins.tools._verification import VerificationCheck, bind_checks, render_verification_status
from tests.test_agent_team_verification import add_job, make_bound, planned_items
from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

DOC = "cv2:" + "a" * 64
REF = "eref:" + "b" * 64 + ":0"
TEXT = "每个加速器约需20–25TB。\n实际部署情况和缓存保留时长仍是重要变量。"
COVERAGE = {"processing": "partial", "availability": "unknown",
            "purity": {"scope": "bounded_candidates_not_corpus_absence"},
            "native": {"unknown_date_sources": ["c" * 64]}}


async def observed_search():
    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    payload = {"ok": True, "coverage": COVERAGE, "hits": [{
        "doc_id": DOC, "evidence_contract": "native-search-evidence-v2",
        "excerpts": [{"text": TEXT, "ref": REF}],
        "preview": "PREVIEW IS NOT EVIDENCE", "scope_ref": "sref:" + "b" * 64,
    }]}
    for query in ["storage", "storage estimate"]:
        await observer.on_tool_result(ctx, ToolResult(
            name="corpus_search", args={"query": query}, result=json.dumps(payload),
            duration_ms=1, tool_call_id=query, is_error=False,
        ))
    result = AgentLoopResult(messages=[], final_content="Report with broken chunk:native1/a:body:0000")
    await observer.on_loop_end(result)
    return result.metadata


async def test_exact_search_evidence_reaches_verifier_even_if_report_damages_locator(tmp_path):
    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata.update(await observed_search())
    checks, prompt = bind_checks([spec], bus=bus, task_id="run", work_items=planned_items(),
                                 required=True, outputs_root=tmp_path)
    assert REF in prompt, "the tool's original reference must bypass model-written report locators"
    assert TEXT in prompt
    assert prompt.count(TEXT) == 1, "repeat queries must not duplicate the same original excerpt"
    assert "PREVIEW IS NOT EVIDENCE" not in prompt
    assert checks[0]["evidence"][0].get("corpus_evidence_sha256")


def test_bound_scope_is_compact_without_weakening_limits(tmp_path):
    bus, spec, _ = make_bound(tmp_path)
    observations = [{"tool": "corpus_search", "source": f"query-{i}", "obtained": True,
                     "coverage": {**COVERAGE, "diagnostic": "x" * 1500}} for i in range(40)]
    bus._jobs["source"].result.metadata["content_acquisition"] = observations
    specs = [VerificationCheck.model_validate({**spec.model_dump(), "check_id": f"c{i}"}) for i in range(3)]
    plans = [{"id": "t1", "verification_required": True, "verification_requirements": [
        {"check_id": s.check_id, "criterion": s.criterion} for s in specs]}]
    checks, prompt = bind_checks(specs, bus=bus, task_id="run", work_items=plans,
                                 required=True, outputs_root=tmp_path)
    assert len(prompt) < 16000
    assert "bounded_candidates_not_corpus_absence" in prompt
    assert bus._jobs["source"].result.metadata["content_acquisition"] == observations
    assert all(c["evidence"][0].get("corpus_limits") for c in checks)


def test_status_does_not_replay_old_full_metadata(tmp_path):
    bus, _, checks = make_bound(tmp_path)
    checks[0]["evidence"][0]["corpus_limits"] = [
        {"tool": "corpus_search", "coverage": COVERAGE, "diagnostic": "x" * 10000}]
    checks[0]["subject"]["text"] = "draft" * 10000
    add_job(bus, "review", checks)
    rendered = render_verification_status(bus, "run")
    assert len(rendered) < 4000, "status must project IDs/verdicts, not echo bound source bodies"
    assert checks[0]["binding_id"] in rendered
    assert "unchecked" in rendered
    assert len(bus._jobs["review"].item.metadata["verification_checks"][0]["subject"]["text"]) == 50000


async def test_persisted_search_reference_remains_resolvable_after_handoff(tmp_path, monkeypatch):
    from plugins.corpus.search_refs import canonical_locator, compact_hit
    from tests.test_corpus_search_refs import original

    monkeypatch.setenv("CORPUS_SEARCH_REF_ROOT", str(tmp_path / "refs"))
    full = original(text=TEXT)
    hit = compact_hit(full)
    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    await observer.on_tool_result(ctx, ToolResult(name="corpus_search", args={"query": "storage"},
        result=json.dumps({"ok": True, "hits": [hit]}), duration_ms=0, tool_call_id="ref", is_error=False))
    packet = ctx.metadata["corpus_evidence"][0]
    assert packet["locator"] == hit["excerpts"][0]["ref"]
    assert canonical_locator(packet["doc_id"], packet["locator"]) == full["locator"]
    assert packet["text"] == TEXT


@pytest.mark.parametrize("payload", [
    {"ok": False, "hits": []},
    {"ok": True, "hits": [{"doc_id": DOC, "preview": TEXT}]},
    {"ok": True, "hits": [{"doc_id": DOC, "snippet": TEXT}]},
])
async def test_preview_and_failed_search_never_become_handoff_evidence(payload):
    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    await observer.on_tool_result(ctx, ToolResult(name="corpus_search", args={},
        result=json.dumps(payload), duration_ms=0, tool_call_id="ref", is_error=False))
    assert ctx.metadata["corpus_evidence"] == []


async def test_fetch_fragments_preserve_original_locator_and_pagination():
    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    locator = "chunk:native1/" + "a" * 16 + "%3Abody%3A0000/0123456789abcdef"
    item = {"locator": locator, "text": TEXT, "fragment": {"start": 10, "end": 10 + len(TEXT)},
            "evidence_ref": "ce:" + "d" * 32, "kind": "body"}
    await observer.on_tool_result(ctx, ToolResult(name="corpus_fetch", args={},
        result=json.dumps({"ok": True, "doc_id": DOC, "items": [item], "next_cursor": "cpage:" + "e" * 32}),
        duration_ms=0, tool_call_id="ref", is_error=False))
    packet = ctx.metadata["corpus_evidence"][0]
    assert packet["locator"] == locator
    assert packet["fragment"] == item["fragment"]
    assert packet["next_cursor"].startswith("cpage:")
    assert packet["evidence_ref"] != packet["locator"]


def test_handoff_budget_prefers_cited_ref_and_never_cuts_qualification():
    from plugins.tools._corpus_handoff import render_corpus_handoff

    records = [{"doc_id": DOC, "locator": f"eref:{'a'*64}:{i}", "text": f"Other {i}:" + "x" * 1000}
               for i in range(50)]
    records.append({"doc_id": DOC, "locator": REF, "text": TEXT})
    prompt = render_corpus_handoff({"source": records}, reference_text="cite " + REF)
    assert TEXT in prompt
    assert len(prompt) < 35000
    assert "Omitted excerpt bodies:" in prompt
    assert prompt.index(REF) < prompt.index("Other 0:")
