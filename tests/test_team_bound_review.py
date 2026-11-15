"""Check dispatch consumes its bound evidence without reopening research."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.task_board import add_task
from tests.test_agent_team_verification import add_job
from tests.test_team_verification_admission import admission_run as _admission_run

admission_run = _admission_run


async def test_bound_review_cannot_inherit_unbound_research_instructions(admission_run, monkeypatch):
    from frontier_agent.components.agent_bus import bus as bus_module
    from plugins.tools.collect_reports import collect_reports
    from plugins.tools.corpus_fetch import corpus_fetch
    from plugins.tools.corpus_search import corpus_search

    bus, _ = admission_run
    captured = []
    previous = bus_module.run_agent_loop

    async def capture(**kwargs):
        captured.append(kwargs)
        return await previous(**kwargs)

    monkeypatch.setattr(bus_module, "run_agent_loop", capture)
    bus.get_session("run::reviewer").tools = [corpus_search, corpus_fetch]
    bus.get_session("run::reviewer").system_prompt = "UNBOUND_ROLE: Investigate all related topics"
    await add_task.func([{
        "description": "Check requested observation", "kind": "verification",
        "verification_requirements": [{"check_id": "citations", "criterion": "Check exact candidate"}],
    }])
    add_job(bus, "source", [])
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "reviewer", "prompt": "UNBOUND_RESEARCH: Read every source and rank alternatives",
        "verification_checks": [{
            "check_id": "citations", "subject": {"text": "Requested observation"},
            "evidence": [{"job_id": "source"}],
        }],
    }])
    assert not reply.startswith("Error"), reply
    await collect_reports.func(timeout=2)
    assert captured
    assert "UNBOUND_RESEARCH" not in captured[0]["user_message"]
    assert "UNBOUND_ROLE" not in captured[0]["system_prompt"]
    names = {t.name for t in captured[0]["tools"]}
    assert "corpus_fetch" not in names and "corpus_search" not in names
    assert "read_bound_evidence" in names


async def packet_for(tmp_path, *, text="Original condition", reads=None, records=None, web=False):
    from plugins.tools._bound_evidence import build_review_packet
    from plugins.tools._verification import bind_checks
    from tests.test_agent_team_verification import make_bound, planned_items

    bus, spec, _ = make_bound(tmp_path)
    metadata = bus._jobs["source"].result.metadata
    metadata["web_evidence" if web else "corpus_evidence"] = records if records is not None else [{
        "doc_id": "cv2:" + "a" * 64, "locator": "chunk:document1/unit",
        "text": text, "evidence_ref": "ce:" + "b" * 32,
    }]
    if reads:
        metadata["corpus_document_reads"] = reads
    checks, _ = bind_checks([spec], bus=bus, task_id="run", work_items=planned_items(),
                           required=True, outputs_root=tmp_path)
    return bus, checks, build_review_packet(checks, bus=bus, task_id="run")


async def test_document_read_receipt_survives_source_handoff_without_claiming_pdf_coverage(tmp_path):
    from frontier_agent.core.loop_types import AgentLoopResult, ToolResult
    from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    result = {
        "ok": True, "scope": "document", "doc_id": "cv2:" + "a" * 64,
        "document_sha256": "d" * 64, "total_units": 1,
        "position": {"unit_index": 1, "offset": 0}, "fetch_complete": True,
        "source_coverage": "unknown", "coverage_scope": "document_units", "items": [],
    }
    await observer.on_tool_result(ctx, ToolResult(
        "corpus_fetch", {"scope": "document"}, json.dumps(result), 0, "read-1", False,
    ))
    completed = AgentLoopResult(messages=[], final_content="Read complete")
    await observer.on_loop_end(completed)
    reads = completed.metadata.get("corpus_document_reads")
    assert reads, "a source's complete-read receipt must not vanish into its prose report"
    _, checks, packet = await packet_for(tmp_path, reads=reads)
    assert checks[0]["evidence"][0]["corpus_document_reads_sha256"]
    assert packet["sources"]["source"]["document_reads"][0]["source_coverage"] == "unknown"


async def test_bound_snapshot_pages_reconstruct_original_without_any_live_read(tmp_path):
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.read_bound_evidence import read_bound_evidence

    original = ('A qualification: "保留条件"\n' * 900)
    bus, checks, packet = await packet_for(tmp_path, text=original)
    bus._jobs["source"].result.metadata["corpus_evidence"][0]["text"] = "CHANGED AFTER DISPATCH"
    token = set_verification_scope("review", {"verification_checks": checks, "verification_packet": packet})
    try:
        args = {"binding_id": checks[0]["binding_id"], "source_key": "source"}
        chunks = []
        while True:
            raw = await read_bound_evidence.func(**args)
            assert len(raw) <= 6000
            payload = json.loads(raw)
            assert payload["ok"] and payload["fresh_observation"] is False
            assert payload["source_availability"] == "not_rechecked"
            chunks.append(payload["record"]["text"])
            if payload["next"] is None:
                break
            args.update(payload["next"])
        assert "".join(chunks) == original
        bad = json.loads(await read_bound_evidence.func(binding_id="another-job", source_key="source"))
        assert bad["code"] == "unbound_source"
    finally:
        reset_verification_scope(token)
    assert json.loads(await read_bound_evidence.func(binding_id="x", source_key="source"))["code"] == "no_verification_scope"


def test_research_session_keeps_full_acquisition_capability():
    from frontier_agent.components.agent_bus.models import SubTask
    from plugins.tools.corpus_fetch import corpus_fetch
    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    runtime = build_swarm_session_runtime_spec(SwarmSubagentRuntime(), session_name="reader", task_id="run")
    tools = [corpus_fetch]
    assert runtime.tools_builder(SubTask("Read the full document"), tools) == tools
    review = runtime.tools_builder(SubTask("Check", metadata={"verification_checks": [{"check_id": "c"}]}), tools)
    assert corpus_fetch not in review
    assert runtime.tools_builder(SubTask("Later research job"), tools) == tools


async def test_missing_evidence_can_be_acquired_and_rebound_without_waiving_check(admission_run, monkeypatch):
    from frontier_agent.components.agent_bus import bus as bus_module
    from frontier_agent.core.loop_types import AgentLoopResult
    from plugins.tools._verification import get_verification_scope, project_bus_checks
    from plugins.tools.collect_reports import collect_reports
    from plugins.tools.read_bound_evidence import read_bound_evidence
    from plugins.tools.submit_report import submit_report
    from tests.test_agent_team_verification import verdict_for

    bus, _ = admission_run

    async def review(**kwargs):
        scope = get_verification_scope()
        check = scope.checks[0]
        key = check["evidence"][0]["key"]
        payload = json.loads(await read_bound_evidence.func(binding_id=check["binding_id"], source_key=key))
        sufficient = payload.get("ok") and payload["record"]["text"] == "Required condition"
        receipt = await submit_report.func("Evidence reviewed", verification_results=[verdict_for(
            check, verdict="pass" if sufficient else "unchecked", evidence_keys=[key],
            method="Inspect bound original", detail="Condition present" if sufficient else "Condition absent",
            unresolved_issues=[] if sufficient else ["Required condition has no captured source text"],
        )])
        assert not receipt.startswith("Error"), receipt
        return AgentLoopResult(messages=[], final_content="Review recorded", stopped_by="submit_report")

    monkeypatch.setattr(bus_module, "run_agent_loop", review)
    await add_task.func([{
        "description": "Check exact candidate", "kind": "verification",
        "verification_requirements": [{"check_id": "condition", "criterion": "Check required condition"}],
    }])
    add_job(bus, "source", [])
    spec = {"check_id": "condition", "subject": {"text": "Required condition"}, "evidence": [{"job_id": "source"}]}
    first = await agent_team_assign_task.func(tasks=[{"agent": "reviewer", "prompt": "Check", "verification_checks": [spec]}])
    assert not first.startswith("Error"), first
    await collect_reports.func(timeout=2)
    old = project_bus_checks(bus, "run")["checks"][0]
    assert old["verdict"] == "unchecked"
    assert old["result"]["unresolved_issues"]
    # Research supplies new original evidence; it is not a changed reviewer instruction.
    add_job(bus, "repaired-source", [])
    bus._jobs["repaired-source"].result.metadata["corpus_evidence"] = [{
        "doc_id": "cv2:" + "a" * 64, "locator": "chunk:document1/condition", "text": "Required condition",
    }]
    repaired = {**spec, "evidence": [{"job_id": "repaired-source"}], "replaces_job_id": old["job_id"],
                "revision_kind": "evidence", "revision_reason": "Acquired the missing condition"}
    second = await agent_team_assign_task.func(tasks=[{"agent": "reviewer", "prompt": "Check", "verification_checks": [repaired]}])
    assert not second.startswith("Error"), second
    await collect_reports.func(timeout=2)
    current = project_bus_checks(bus, "run")["checks"][0]
    assert current["verdict"] == "pass" and current["binding_id"] != old["binding_id"]
    assert current["criterion"] == old["criterion"]


async def test_source_changes_between_binding_and_snapshot_are_rejected(tmp_path):
    from plugins.tools._bound_evidence import build_review_packet

    bus, checks, _ = await packet_for(tmp_path)
    bus._jobs["source"].result.metadata["corpus_evidence"][0]["text"] = "Another version"
    with pytest.raises(ValueError, match="bound source version changed"):
        build_review_packet(checks, bus=bus, task_id="run")


async def test_snapshot_keeps_web_extraction_and_partial_coverage_limits(tmp_path):
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.read_bound_evidence import read_bound_evidence

    record = {
        "source": "https://example.test/report", "text": "Extracted condition",
        "sha256": hashlib.sha256(b"Extracted condition").hexdigest(),
        "status": "partial", "content_kind": "focused_extraction",
        "coverage": {"tables": "not_obtained"}, "detail": "Only focused model extraction",
    }
    _, checks, packet = await packet_for(tmp_path, records=[record], web=True)
    token = set_verification_scope("review", {"verification_checks": checks, "verification_packet": packet})
    try:
        payload = json.loads(await read_bound_evidence.func(
            binding_id=checks[0]["binding_id"], source_key="source",
        ))
        assert payload["ok"]
        for field in ("content_kind", "status", "coverage", "detail"):
            assert payload["record"].get(field) == record[field]
    finally:
        reset_verification_scope(token)


async def test_targeted_snapshot_read_does_not_force_enumeration_and_rejects_unknown_sources(tmp_path):
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.read_bound_evidence import read_bound_evidence

    records = [{"doc_id": "cv2:" + "a" * 64, "locator": f"chunk:document1/u{i}", "text": f"condition {i}"} for i in range(3)]
    _, checks, packet = await packet_for(tmp_path, records=records)
    token = set_verification_scope("review", {"verification_checks": checks, "verification_packet": packet})
    try:
        args = {"binding_id": checks[0]["binding_id"], "source_key": "source"}
        payload = json.loads(await read_bound_evidence.func(**args, locator=records[2]["locator"]))
        assert payload["record"]["text"] == "condition 2"
        assert payload["next"] is None
        assert json.loads(await read_bound_evidence.func(**{**args, "source_key": "not-bound"}))["code"] == "unbound_source"
        assert json.loads(await read_bound_evidence.func(**args, record_index=-1))["code"] == "invalid_record_index"
        assert json.loads(await read_bound_evidence.func(**args, offset=10000))["code"] == "invalid_offset"
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize("change_coverage", [False, True])
async def test_new_coverage_can_unlock_recheck_but_new_receipt_alias_cannot(tmp_path, change_coverage):
    from plugins.tools._verification import VerificationCheck, bind_checks
    from tests.test_agent_team_verification import planned_items

    reads = [{"doc_id": "cv2:" + "a" * 64, "document_sha256": "b" * 64,
              "fetch_complete": False, "position": {"unit_index": 1, "offset": 0}, "page_id": "old"}]
    bus, checks, _ = await packet_for(tmp_path, reads=reads)
    add_job(bus, "first-review", checks, verdicts=["unchecked"])
    reads[0]["page_id"] = "new"
    if change_coverage:
        reads[0]["fetch_complete"] = True
        reads[0]["position"] = {"unit_index": 2, "offset": 0}
    spec = VerificationCheck(
        check_id="amount", subject={"job_id": "draft"}, evidence=[{"job_id": "source"}],
        replaces_job_id="first-review", revision_kind="evidence", revision_reason="Updated read receipts",
    )
    if change_coverage:
        rebound, _ = bind_checks([spec], bus=bus, task_id="run", work_items=planned_items(),
                                 required=True, outputs_root=tmp_path)
        assert rebound[0]["binding_id"] != checks[0]["binding_id"]
    else:
        with pytest.raises(ValueError, match="recheck budget"):
            bind_checks([spec], bus=bus, task_id="run", work_items=planned_items(),
                        required=True, outputs_root=tmp_path)


# W1: a handoff ref names a model research product; its captured originals stay
# version-pinned in the background and are read on demand, never fetched again.

HANDOFF_REF = "/outputs/scratch/handoffs/report.md"


def sample_originals():
    return [
        {
            "doc_id": "cv2:" + "a" * 64,
            "locator": f"chunk:document1/unit{i}",
            "text": f"condition {i} with its unit and qualification",
            "content_kind": "original",
            "coverage": {"tables": "not_obtained"},
        }
        for i in range(3)
    ]


def handoff_packet(
    records,
    *,
    ref="",
    max_inline_records=2,
    reads=None,
    empty_version=False,
    observed=None,
):
    """Build a packet for a job report or one of its file handoffs, fully offline."""
    from plugins.tools._bound_evidence import build_review_packet, digest

    key = "producer" + (f"::{ref}" if ref else "")
    source = {
        "key": key,
        "job_id": "producer",
        "sha256": "report",
        "corpus_evidence_sha256": digest([] if empty_version else records),
    }
    if ref:
        source["ref"] = ref
    if reads is not None:
        source["corpus_document_reads_sha256"] = digest(reads)
    checks = [{
        "binding_id": "binding-1", "check_id": "condition", "work_item_id": "t1",
        "subject": {"key": "inline:candidate", "text": "candidate"}, "evidence": [source],
    }]
    metadata = {
        "corpus_evidence": [] if empty_version else (records if observed is None else observed)
    }
    if reads is not None:
        metadata["corpus_document_reads"] = reads
    bus = SimpleNamespace(
        get_job_result=lambda task_id, job_id: (None, SimpleNamespace(metadata=metadata))
    )
    packet = build_review_packet(
        checks, bus=bus, task_id="run", max_inline_records=max_inline_records
    )
    return checks, packet


async def test_job_and_handoff_bindings_read_the_same_captured_version():
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.read_bound_evidence import read_bound_evidence

    records = sample_originals()
    job_checks, job_packet = handoff_packet(records)
    ref_checks, ref_packet = handoff_packet(records, ref=HANDOFF_REF)
    job_key = job_checks[0]["evidence"][0]["key"]
    ref_key = ref_checks[0]["evidence"][0]["key"]
    assert (job_packet["sources"][job_key]["snapshot"]["sha256"]
            == ref_packet["sources"][ref_key]["snapshot"]["sha256"])
    for checks, packet, key in (
        (job_checks, job_packet, job_key), (ref_checks, ref_packet, ref_key),
    ):
        token = set_verification_scope("review", {
            "verification_checks": checks, "verification_packet": packet,
        })
        try:
            payload = json.loads(await read_bound_evidence.func(
                binding_id="binding-1", source_key=key, locator=records[2]["locator"],
            ))
        finally:
            reset_verification_scope(token)
        assert payload["ok"] and payload["record"]["text"] == records[2]["text"]
        assert payload["fresh_observation"] is False
        assert payload["source_availability"] == "not_rechecked"


async def test_display_excerpt_keeps_background_originals_readable():
    from plugins.tools._bound_evidence import packet_index
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.read_bound_evidence import read_bound_evidence

    records = sample_originals()
    checks, packet = handoff_packet(records, ref=HANDOFF_REF)
    key = checks[0]["evidence"][0]["key"]
    index = packet_index(packet)
    entry = index["sources"][key]
    assert entry["inline_record_count"] == 0 and entry["record_count"] == 3
    assert entry["selection_mode"] == "on_demand"
    assert entry["report_content_kind"] == "model_research_product"
    assert records[2]["text"] not in json.dumps(index)
    token = set_verification_scope("review", {
        "verification_checks": checks, "verification_packet": packet,
    })
    try:
        payload = json.loads(await read_bound_evidence.func(
            binding_id="binding-1", source_key=key, locator=records[2]["locator"],
        ))
    finally:
        reset_verification_scope(token)
    assert payload["ok"] and payload["record_source"] == "bound_snapshot"
    assert payload["record"]["text"] == records[2]["text"]
    assert payload["record"]["locator"] == records[2]["locator"]
    assert payload["record"]["content_kind"] == "original"
    assert payload["record"]["coverage"] == {"tables": "not_obtained"}


@pytest.mark.parametrize("inline", [False, True])
async def test_snapshot_tampering_is_a_typed_failure(inline):
    from plugins.tools._verification import reset_verification_scope, set_verification_scope
    from plugins.tools.read_bound_evidence import read_bound_evidence

    records = sample_originals()
    checks, packet = handoff_packet(
        records,
        ref="" if inline else HANDOFF_REF,
        max_inline_records=160 if inline else 2,
    )
    key = checks[0]["evidence"][0]["key"]
    target = (packet["sources"][key]["records"] if inline
              else packet["sources"][key]["snapshot"]["records"])
    target[0]["text"] = "CHANGED AFTER DISPATCH"
    token = set_verification_scope("review", {
        "verification_checks": checks, "verification_packet": packet,
    })
    try:
        payload = json.loads(await read_bound_evidence.func(
            binding_id="binding-1", source_key=key,
        ))
    finally:
        reset_verification_scope(token)
    assert payload["code"] == "snapshot_version_changed"
    assert payload["fresh_observation"] is False


def test_declared_originals_without_readable_records_fails_at_dispatch():
    with pytest.raises(ValueError, match="no readable captured originals"):
        handoff_packet([], ref=HANDOFF_REF, empty_version=True)


def test_handoff_binding_rejects_a_changed_source_version():
    records = sample_originals()
    changed = [dict(record, text="ANOTHER VERSION") for record in records]
    with pytest.raises(ValueError, match="bound source version changed"):
        handoff_packet(records, ref=HANDOFF_REF, observed=changed)


def test_handoff_file_is_not_presented_as_captured_originals():
    checks, packet = handoff_packet(sample_originals(), ref=HANDOFF_REF)
    key = checks[0]["evidence"][0]["key"]
    snapshot = packet["sources"][key]["snapshot"]
    assert snapshot["content_kind"] == "captured_tool_observations"
    assert snapshot["report_content_kind"] == "model_research_product"
    assert snapshot["origin_job_id"] == "producer"
    assert snapshot["handoff_ref"] == HANDOFF_REF
    assert all(record.get("text") != HANDOFF_REF for record in snapshot["records"])


def test_handoff_snapshot_is_not_priced_as_zero_or_unbounded_work():
    from plugins.tools._verification import (
        ON_DEMAND_ADMISSION_FLOOR_RECORDS,
        packet_record_count,
        packet_workload_records,
    )

    records = sample_originals()
    _, job_packet = handoff_packet(records)
    _, ref_packet = handoff_packet(records, ref=HANDOFF_REF)
    # On-demand readback depends on packet size, not on a handoff attachment:
    # an unselected large job must never inline all of its captured originals.
    for packet in (job_packet, ref_packet):
        entry = next(iter(packet["sources"].values()))
        assert entry["selection_mode"] == "on_demand"
        assert packet_record_count(packet) == 0
        assert entry["snapshot"]["record_count"] == len(records)
    assert packet_workload_records(ref_packet) == packet_workload_records(job_packet) == 3
    assert 0 < packet_workload_records(ref_packet) <= ON_DEMAND_ADMISSION_FLOOR_RECORDS


# --- W6: explicit evidence selection (two-layer interface) -------------------


def _captured_metadata(refs):
    return {
        "corpus_evidence": [
            {
                "doc_id": "cv2:" + "a" * 64,
                "locator": f"chunk:document1/unit{i}",
                "evidence_ref": ref,
                "text": f"condition {i} with unit, date and qualifier",
                "content_kind": "original",
                "coverage": {"tables": "not_obtained"},
            }
            for i, ref in enumerate(refs)
        ]
    }


def test_illegal_evidence_ref_fails_before_dispatch():
    from plugins.tools._verification import VerificationSource, _resolve_evidence_refs

    meta = _captured_metadata(["ce:aaa", "ce:bbb"])
    with pytest.raises(ValueError, match="not captured by job"):
        _resolve_evidence_refs(
            VerificationSource(job_id="producer", evidence_refs=["ce:invented"]), meta,
        )


def test_evidence_refs_cannot_be_borrowed_across_jobs():
    from plugins.tools._verification import VerificationSource, _resolve_evidence_refs

    meta_a = _captured_metadata(["ce:aaa"])
    meta_b = _captured_metadata(["ce:bbb"])
    with pytest.raises(ValueError, match="not captured by job"):
        _resolve_evidence_refs(
            VerificationSource(job_id="job_b", evidence_refs=["ce:aaa"]), meta_b,
        )
    assert _resolve_evidence_refs(
        VerificationSource(job_id="job_a", evidence_refs=["ce:aaa"]), meta_a,
    ) == ["chunk:document1/unit0"]


def test_two_checks_select_different_small_ranges_from_one_large_job():
    """The same 200-record job serves two checks without colliding keys."""
    from plugins.tools._bound_evidence import build_review_packet, digest, packet_index
    from plugins.tools._verification import packet_record_count

    refs = [f"ce:ref{i}" for i in range(200)]
    meta = _captured_metadata(refs)
    bus = SimpleNamespace(
        get_job_result=lambda task_id, job_id: (
            None, SimpleNamespace(final_content="Report body", metadata=meta),
        )
    )
    first = {
        "key": "producer::sel:first", "job_id": "producer",
        "corpus_evidence_sha256": digest(meta["corpus_evidence"]),
        "record_locators": ["chunk:document1/unit0", "chunk:document1/unit1"],
    }
    second = {
        "key": "producer::sel:second", "job_id": "producer",
        "corpus_evidence_sha256": digest(meta["corpus_evidence"]),
        "record_locators": ["chunk:document1/unit100", "chunk:document1/unit101"],
    }
    checks = [
        {"binding_id": "b1", "subject": {"key": "inline:a", "text": "candidate one"},
         "evidence": [first]},
        {"binding_id": "b2", "subject": {"key": "inline:b", "text": "candidate two"},
         "evidence": [second]},
    ]
    packet = build_review_packet(checks, bus=bus, task_id="run")
    assert len(packet["sources"]) == 2
    for source in packet["sources"].values():
        assert source["selection_mode"] == "selected"
        assert len(source["records"]) == 2
        assert source["snapshot"]["record_count"] == 200
        assert all(r.get("content_kind") == "original" for r in source["records"])
        assert all(r.get("coverage") for r in source["records"])
    assert packet_record_count(packet) == 4
    assert all(
        entry["snapshot_record_count"] == 200
        for entry in packet_index(packet)["sources"].values()
    )


def test_model_evidence_refs_resolve_to_distinct_internal_handles(tmp_path):
    """Model supplies refs; runtime produces stable keys and internal locators."""
    from plugins.tools._bound_evidence import build_review_packet
    from plugins.tools._verification import VerificationCheck, bind_checks

    refs = [f"ce:ref{i}" for i in range(20)]
    meta = _captured_metadata(refs)
    bus = SimpleNamespace(
        get_job_result=lambda task_id, job_id: (
            None, SimpleNamespace(final_content="Report body", metadata=meta),
        ),
        list_task_jobs=lambda *_: [],
    )
    work_items = [{
        "id": "t1",
        "verification_required": True,
        "verification_requirements": [
            {"check_id": "c1", "criterion": "check one"},
            {"check_id": "c2", "criterion": "check two"},
        ],
    }]
    specs = [
        VerificationCheck(
            check_id="c1", subject={"text": "candidate one"},
            evidence=[{"job_id": "producer", "evidence_refs": ["ce:ref0"]}],
        ),
        VerificationCheck(
            check_id="c2", subject={"text": "candidate two"},
            evidence=[{"job_id": "producer", "evidence_refs": ["ce:ref10"]}],
        ),
    ]
    bound, _ = bind_checks(
        specs, bus=bus, task_id="run", work_items=work_items,
        required=True, outputs_root=tmp_path,
    )
    first, second = (check["evidence"][0] for check in bound)
    assert first["key"] != second["key"]
    assert "ce:ref0" not in first["key"] and "unit0" not in first["key"]
    assert first["record_locators"] == ["chunk:document1/unit0"]
    assert second["record_locators"] == ["chunk:document1/unit10"]
    packet = build_review_packet(bound, bus=bus, task_id="run")
    assert len(packet["sources"]) == 2
    assert all(s["selection_mode"] == "selected" for s in packet["sources"].values())
