"""Exercise citation readability through delivery and both publication boundaries.

The source is synthetic; receipts, manifests, ledger delivery and final report
checks are real. No model or external corpus service is called.
"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.execution_context import get_current_execution_scope
from plugins.corpus.final_delivery import corpus_citation_readability_issue
from plugins.corpus.ledger import (
    get_run_ledger,
    load_manifest_files,
    publish_boundary,
    reset_run_ledgers,
)
from plugins.corpus.tool_refs import (
    fetch_evidence_ref,
    publish_fetch_references,
    resolve_evidence_reference,
)
from plugins.tools.corpus_manifest import corpus_submit_manifest
from tests.test_agent_team_verification import add_job, binding
from tests.test_corpus_manifest_tool import DOC, TEXT, _fetch_body, run_env
from tests.test_report_citation_readability import context
from tests.test_team_atomic_delivery import delivery_run
from workflows.agent_team.delivery import deliver_answer
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.lifecycle import wind_down_team
from workflows.agent_team.observers.bare_text_finalize import BareTextFinalizeObserver

# Expose the shared fixtures without letting lint mistake them for unused imports.
__all__ = ["delivery_run", "run_env"]


@pytest.fixture
def corpus(run_env, monkeypatch):
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(run_env / "receipts"))
    monkeypatch.setenv("CORPUS_TARGET_DB", "readability-test")
    monkeypatch.setenv("A4_ENFORCE", "off")
    payload = json.loads(_fetch_body())
    reference = fetch_evidence_ref(DOC, payload)
    payload["evidence_ref"] = reference
    body = publish_fetch_references(json.dumps(payload, ensure_ascii=False))
    ledger = get_run_ledger()
    ledger.record_fetch_result(body)
    ledger.finalize([{"role": "tool", "content": body}])
    readable = f"{TEXT}（来源：示例财报，营业收入节。）"
    raw = f"{TEXT}（来源：`{reference}`。）"

    def conclusions(text):
        return [{
            "id": "revenue", "report_quote": text,
            "evidence": [{"evidence_ref": reference, "purpose": "value"}],
        }]

    yield SimpleNamespace(
        ledger=ledger, reference=reference, readable=readable, raw=raw,
        conclusions=conclusions,
        resolver=lambda doc, loc: TEXT if (doc, loc) == (DOC, "chunk:c1") else None,
    )
    reset_run_ledgers()


async def final_report(bus, corpus, body, stopped_by="final_answer"):
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    report = finalize_team_report(
        body, source="agent", answer_status="complete", stopped_by=stopped_by,
        question="解释营业收入", wind_down=wind.as_dict(),
    )
    boundary = publish_boundary(
        corpus.ledger, final_text=report["final_answer"],
        answer_status=report["answer_status"], resolver=corpus.resolver,
    )
    return report, boundary


def checked_passage(bus, text):
    check = binding()
    check["publication_excerpt"] = True
    check["subject"].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    add_job(bus, "review", [check], verdicts=["pass"])


@pytest.mark.parametrize("route", ["deliver_answer", "bare_text", "repaired_bare_text"])
async def test_readable_publication_preserves_real_evidence_and_checked_passage(
    delivery_run, corpus, route,
):
    bus, _ = delivery_run
    checked_passage(bus, corpus.readable)
    original_evidence = resolve_evidence_reference(corpus.reference)
    if route == "deliver_answer":
        await deliver_answer.func(
            content=corpus.readable, corpus_conclusions=corpus.conclusions(corpus.readable),
        )
    else:
        # Bare text relies on an explicitly submitted manifest. Do not fabricate
        # evidence rebinding in the observer or reuse a member's stale anchors.
        submitted = json.loads(await corpus_submit_manifest.func(
            conclusions=corpus.conclusions(corpus.readable),
        ))
        assert submitted["ok"] and submitted["evidence_status"] == "verified"
        observer = BareTextFinalizeObserver()
        if route == "repaired_bare_text":
            repair = await observer.on_llm_response(context(corpus.raw))
            assert repair.continue_to_next_turn
            assert "delivery_record" not in get_current_execution_scope().metadata
        accepted = await observer.on_llm_response(context(corpus.readable, turn=2))
        assert accepted.stop_reason == "final_answer"

    record = get_current_execution_scope().metadata["delivery_record"]
    assert record["content"] == corpus.readable
    manifests = {path: path.read_bytes() for path, _ in load_manifest_files()}
    assert manifests
    report, boundary = await final_report(bus, corpus, record["content"])
    assert boundary["final_text"] == corpus.readable
    assert boundary["publish_status"] == "verified"
    assert boundary["answer_status"] == "complete"
    assert corpus_citation_readability_issue(boundary["final_text"]) is None
    assert report["report_contract"]["publication"]["unmatched_checked_excerpts"] == []
    assert report["report_contract"]["verification_checks"][0]["verdict"] == "pass"
    assert resolve_evidence_reference(corpus.reference) == original_evidence
    assert original_evidence["quote"] == TEXT
    assert all(path.read_bytes() == before for path, before in manifests.items())
    row = load_manifest_files()[0][1]["conclusions"][0]
    assert row["report_quote"] == corpus.readable
    assert row["evidence"][0]["quote"] == TEXT


async def test_readability_revision_cannot_reuse_an_old_report_anchor(delivery_run, corpus):
    with pytest.raises(ValueError, match="corpus_citation_readability"):
        await deliver_answer.func(
            content=corpus.raw, corpus_conclusions=corpus.conclusions(corpus.raw),
        )
    with pytest.raises(ValueError, match="corpus_manifest_anchor_mismatch"):
        await deliver_answer.func(content=corpus.readable, base_version=1, revise_content=True)
    assert load_manifest_files() == []
    assert "delivery_record" not in get_current_execution_scope().metadata
    assert resolve_evidence_reference(corpus.reference)["quote"] == TEXT


async def test_changing_checked_citation_requires_a_recheck(delivery_run, corpus):
    bus, _ = delivery_run
    checked_passage(bus, corpus.raw)
    with pytest.raises(ValueError, match="checked_publication_excerpt_missing"):
        await deliver_answer.func(
            content=corpus.readable, corpus_conclusions=corpus.conclusions(corpus.readable),
        )
    assert load_manifest_files() == []
    report, _ = await final_report(bus, corpus, corpus.readable)
    assert report["answer_status"] == "partial"
    assert report["report_contract"]["publication"]["unmatched_checked_excerpts"] == ["amount"]
    assert "checked_publication_excerpt_changed" in {
        gap["code"] for gap in report["report_contract"]["gaps"]
    }


@pytest.mark.parametrize("route", ["repair_exhausted", "last_turn", "budget_exhausted"])
async def test_unresolved_readability_reaches_the_published_report_contract(
    delivery_run, corpus, route,
):
    bus, _ = delivery_run
    # A valid evidence chain is deliberately insufficient to certify readability.
    submitted = json.loads(await corpus_submit_manifest.func(
        conclusions=corpus.conclusions(corpus.raw),
    ))
    assert submitted["evidence_status"] == "verified"
    observer = BareTextFinalizeObserver()
    if route != "last_turn":
        draft = context(corpus.raw)
        repair = await observer.on_llm_response(draft)
        assert repair.continue_to_next_turn
    if route == "budget_exhausted":
        # The rejected draft is all that remains when no further turn can run.
        body = draft.metadata["final_answer_candidate"]
        stopped_by = "budget_exhausted"
    else:
        draft = context(corpus.raw, turn=5 if route == "last_turn" else 2)
        accepted = await observer.on_llm_response(draft)
        assert accepted.stop_reason == "final_answer"
        body = draft.metadata["final_answer"]
        stopped_by = accepted.stop_reason
    assert draft.metadata["corpus_citation_readability"] == "unresolved"
    report, boundary = await final_report(bus, corpus, body, stopped_by)
    assert boundary["publish_status"] == "verified"
    assert corpus.raw in boundary["final_text"]  # Never silently erase evidence.
    assert resolve_evidence_reference(corpus.reference)["quote"] == TEXT
    assert "corpus_citation_readability" in {
        gap["code"] for gap in report["report_contract"]["gaps"]
    }, "08 acceptance 6: evidence validity must not hide unresolved report readability"
    assert report["answer_status"] != "complete"
    assert "部分出处仍使用内部定位符" in boundary["final_text"]
    if route != "budget_exhausted":
        assert "尚有任务或证据缺口" not in boundary["final_text"]
