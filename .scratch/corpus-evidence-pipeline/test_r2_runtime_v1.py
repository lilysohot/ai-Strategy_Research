"""P2-B public interface and durable offline audit fault tests, all synthetic."""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from threading import Barrier

import p2b_guard
import pytest
from p2b_guard import check_inventory
from p2b_projection import project

from plugins.corpus import _r2_runtime as runtime
from plugins.corpus._r2_audit import AuditJournal, AuditSnapshot, OfflineGrant
from plugins.corpus._r2_plan import Scope, digest
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun, build_evidence_run


def fixture(texts: tuple[str, ...] = ("甲公司预计增产。", "乙公司预计减产。")) -> runtime.Prepared:
    doc = EvidenceDocument(
        doc_id="synthetic",
        title="synthetic",
        source_path="synthetic.md",
        source_rev="synthetic-rev",
        parse_rev="synthetic-parse",
        parser_version="test",
        subject=None,
        published=None,
        pages=(),
        packets=tuple(
            EvidencePacket(packet_id=f"p{i}", locator=f"line:{i}", kind="prose", text=text)
            for i, text in enumerate(texts)
        ),
    )
    run = EvidenceRun(run_id="", document=doc, facts=(), packet_runs=())
    payload = run.model_dump(mode="json")
    payload.pop("run_id")
    run = run.model_copy(update={"run_id": fingerprint(payload)})
    return runtime.prepare(
        run,
        tuple(Scope(p.packet_id, 0, len(p.text)) for p in doc.packets),
        expected_evidence_sha=digest(run.model_dump(mode="json")),
    )


class FakeAdapter:
    mode = "fake"

    def __init__(self, mutation: str = "", decision: str = "present") -> None:
        self.mutation = mutation
        self.decision = decision
        self.calls = 0

    def respond(self, request: str) -> str:
        self.calls += 1
        if self.mutation == "exception":
            raise RuntimeError("private provider error")
        payload = json.loads(request)
        rows = []
        for task in payload["obligations"]:
            if payload["task"] == "relations":
                rows.append(
                    {
                        "protocol_version": runtime.PROTOCOL,
                        "plan_id": payload["plan_id"],
                        "obligation_id": task["obligation_id"],
                        "decision": self.decision,
                        "provenance": "source_explicit" if self.decision == "present" else None,
                        "reason": None
                        if self.decision == "present"
                        else "synthetic unknown/negative",
                        "evidence_span_ids": task["evidence_span_ids"],
                    }
                )
                continue
            ref = task["focus"]
            known = {
                "semantic_type": "forecast",
                "perspective": "source_explicit",
                "speech_role": "statement",
                "polarity": "affirmed",
                "statement_role": "claim",
            }
            fields = [
                {
                    "name": axis,
                    "value": known.get(axis),
                    "origin": "model_interpreted" if axis in known else "unknown",
                    "support_span_ids": [ref],
                    "unknown_reason": None if axis in known else "not specified",
                }
                for axis in runtime.AXES
            ]
            rows.append(
                {
                    "protocol_version": runtime.PROTOCOL,
                    "plan_id": payload["plan_id"],
                    "obligation_id": task["obligation_id"],
                    "terminal": "extracted",
                    "reason": None,
                    "evidence_span_ids": [ref],
                    "item": {
                        "item_id": "item-" + task["obligation_id"],
                        "text": payload["spans"][ref]["text"],
                        "constraints": [],
                        "fields": fields,
                        "evidence_span_ids": [ref],
                    },
                }
            )
        if self.mutation == "duplicate":
            rows.append(rows[0])
        elif self.mutation == "missing":
            rows.pop(0)
        elif self.mutation == "unknown_id":
            rows[0]["obligation_id"] = "invented"
        elif self.mutation == "fake_received":
            rows[0]["response_received"] = True
        elif self.mutation == "terminal":
            rows[0]["terminal"] = "partial"
        elif self.mutation == "plan":
            rows[0]["plan_id"] = "wrong"
        elif self.mutation == "evidence":
            rows[0]["evidence_span_ids"] = ["wrong"]
        elif self.mutation == "number":
            for field in rows[0]["item"]["fields"]:
                if field["name"] == "value":
                    field.update(value="999", origin="model_interpreted", unknown_reason=None)
        elif self.mutation == "relation_endpoint":
            rows[0]["from_item"] = "invented"
        elif self.mutation == "relation_provenance":
            rows[0]["provenance"] = "verified_truth"
        raw = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        return raw + ('\n{"truncated":' if self.mutation == "truncated" else "")


def run_case(
    tmp_path: Path, prepared: runtime.Prepared | None = None, mutation: str = ""
) -> tuple[
    runtime.Prepared, runtime.RunResult, AuditSnapshot, runtime.ValidationReport, FakeAdapter
]:
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    prepared = prepared or fixture()
    grant = OfflineGrant(prepared.prepared_id, max_calls=16)
    journal = AuditJournal.create(tmp_path / "audit.sqlite", grant)
    adapter = FakeAdapter(mutation)
    result = runtime.execute(prepared, adapter, journal)
    snapshot = journal.snapshot()
    journal.close()
    report = runtime.validate(
        prepared,
        result,
        snapshot,
        expected_audit_sha=snapshot.sha256,
        expected_result_sha=result.sha256,
    )
    return prepared, result, snapshot, report, adapter


def test_real_md_evidence_bridge_without_model(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.md"
    source.write_text("甲公司预计增产。\n", encoding="utf-8")
    evidence = build_evidence_run(source)
    scopes = tuple(Scope(p.packet_id, 0, len(p.text)) for p in evidence.document.packets if p.text)
    prepared = runtime.prepare(
        evidence, scopes, expected_evidence_sha=digest(evidence.model_dump(mode="json"))
    )
    assert prepared.source.evidence_run_id == evidence.run_id
    assert prepared.source.parse_rev == evidence.document.parse_rev
    with pytest.raises(ValueError):
        runtime.prepare(evidence, scopes, expected_evidence_sha="wrong")
    with pytest.raises(ValueError):
        runtime.prepare(
            evidence.model_copy(update={"run_id": "wrong"}), scopes, expected_evidence_sha="wrong"
        )


def test_positive_execute_validate_and_offline_projection(tmp_path: Path) -> None:
    prepared, result, snapshot, report, adapter = run_case(tmp_path)
    assert adapter.calls == 1
    assert report.protocol_complete and report.audit_verified and report.audit_complete
    assert report.semantic_status == "not_evaluated" and not report.budget_authorized
    assert all(r.response_received for r in result.records)
    source, plan, scored = project(
        prepared,
        result,
        snapshot,
        expected_audit_sha=snapshot.sha256,
        expected_result_sha=result.sha256,
    )
    assert asdict(plan) == asdict(prepared.plan)
    assert scored.audit_complete and source.evidence_run_id == prepared.source.evidence_run_id
    assert scored.records[0].item.text == result.records[0].item.text


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "unknown_id",
        "fake_received",
        "terminal",
        "plan",
        "evidence",
        "number",
        "truncated",
    ],
)
def test_bad_record_does_not_erase_good_sibling(tmp_path: Path, mutation: str) -> None:
    _, result, snapshot, report, _ = run_case(tmp_path, mutation=mutation)
    assert result.records[1].terminal == "extracted"
    assert snapshot.attempts[0].raw
    assert result.errors and not report.protocol_complete


def test_zero_budget_and_unresolved_do_not_send(tmp_path: Path) -> None:
    prepared = fixture(("若需求回升，甲公司增产。",))
    default = runtime.execute(prepared)
    assert default.records[0].terminal == "unresolved"
    grant = OfflineGrant(prepared.prepared_id, max_calls=0)
    journal = AuditJournal.create(tmp_path / "zero.sqlite", grant)
    adapter = FakeAdapter()
    result = runtime.execute(prepared, adapter, journal)
    assert adapter.calls == 0 and not journal.snapshot().attempts
    assert result.records[0].terminal == "unresolved"
    journal.close()


def test_successful_restart_replays_without_resending(tmp_path: Path) -> None:
    prepared, result, snapshot, _, _ = run_case(tmp_path)
    journal = AuditJournal.open(tmp_path / "audit.sqlite", snapshot.grant)
    adapter = FakeAdapter()
    again = runtime.execute(prepared, adapter, journal)
    journal.close()
    assert again == result and adapter.calls == 0


@pytest.mark.parametrize("site", ["after_reserve", "after_response", "after_receipt"])
def test_crash_sites_preserve_budget_and_no_automatic_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site: str
) -> None:
    prepared = fixture()
    grant = OfflineGrant(prepared.prepared_id, max_calls=2)
    path = tmp_path / "crash.sqlite"
    journal = AuditJournal.create(path, grant)
    adapter = FakeAdapter()

    def crash(name: str) -> None:
        if name == site:
            raise SystemExit("simulated process interruption")

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "_checkpoint", crash)
        with pytest.raises(SystemExit):
            runtime.execute(prepared, adapter, journal)
    journal.close()
    journal = AuditJournal.open(path, grant)
    assert len(journal.snapshot().attempts) == 1
    journal.recover_unknown()
    resumed = FakeAdapter()
    result = runtime.execute(prepared, resumed, journal)
    snapshot = journal.snapshot()
    journal.close()
    assert resumed.calls == 0
    if site == "after_receipt":
        assert all(r.terminal == "extracted" for r in result.records)
    else:
        assert snapshot.attempts[0].status == "unknown_outcome"
        assert snapshot.halted == "unknown_outcome"
        assert not any(r.response_received for r in result.records)


def _child_commit_then_exit(path: str, grant: OfflineGrant, received: bool) -> None:
    journal = AuditJournal.open(Path(path), grant)
    number = journal.reserve("frozen-key", "frozen-request")
    if received:
        journal.received(number, "public response", "fake")
    os._exit(23)


@pytest.mark.parametrize("received", [False, True])
def test_real_process_exit_leaves_durable_audit(tmp_path: Path, received: bool) -> None:
    path, grant = tmp_path / "process.sqlite", OfflineGrant("frozen-plan", max_calls=1)
    AuditJournal.create(path, grant).close()
    process = multiprocessing.get_context("fork").Process(
        target=_child_commit_then_exit, args=(str(path), grant, received)
    )
    process.start()
    process.join(10)
    assert not process.is_alive() and process.exitcode == 23
    journal = AuditJournal.open(path, grant)
    snapshot = journal.snapshot()
    assert len(snapshot.attempts) == 1
    assert snapshot.attempts[0].status == ("received" if received else "reserved")
    journal.recover_unknown()
    with pytest.raises(ValueError):
        journal.reserve("frozen-key", "frozen-request")
    journal.close()


def test_concurrent_reservation_has_one_winner(tmp_path: Path) -> None:
    path, grant = tmp_path / "concurrent.sqlite", OfflineGrant("plan", max_calls=1)
    AuditJournal.create(path, grant).close()
    barrier = Barrier(2)

    def worker() -> bool:
        journal = AuditJournal.open(path, grant)
        barrier.wait(timeout=5)
        try:
            journal.reserve("same-key", "same-request")
            return True
        except ValueError:
            return False
        finally:
            journal.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        assert sum(f.result(timeout=10) for f in futures) == 1


@pytest.mark.parametrize("failure", ["adapter", "persistence", "capacity"])
def test_failure_stops_later_batches_and_retains_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    prepared = fixture(tuple(f"公司{i}预计增产。" for i in range(9)))
    journal = AuditJournal.create(
        tmp_path / "failure.sqlite",
        OfflineGrant(
            prepared.prepared_id,
            max_calls=2,
            max_response_bytes=10 if failure == "capacity" else 65536,
        ),
    )
    adapter = FakeAdapter("exception" if failure == "adapter" else "")
    if failure == "persistence":

        def cannot_save(*args: object) -> None:
            raise OSError("simulated disk failure")

        monkeypatch.setattr(journal, "received", cannot_save)
    result = runtime.execute(prepared, adapter, journal)
    snapshot = journal.snapshot()
    journal.close()
    assert adapter.calls == 1 and len(snapshot.attempts) == 1 and snapshot.halted
    assert not result.records[-1].response_received
    if failure == "capacity":
        assert len(snapshot.attempts[0].raw.encode()) > 10  # full response retained, not truncated
    else:
        assert snapshot.attempts[0].raw is None


@pytest.mark.parametrize("failure", ["request", "real_adapter", "plan"])
def test_invalid_inputs_fail_before_reservation(tmp_path: Path, failure: str) -> None:
    prepared = fixture()
    grant = OfflineGrant(
        "wrong" if failure == "plan" else prepared.prepared_id,
        max_calls=1,
        max_request_bytes=2 if failure == "request" else 65536,
    )
    journal = AuditJournal.create(tmp_path / "preflight.sqlite", grant)
    adapter = FakeAdapter()
    if failure == "real_adapter":
        adapter.mode = "real"
    with pytest.raises(ValueError):
        runtime.execute(prepared, adapter, journal)
    assert not journal.snapshot().attempts and adapter.calls == 0
    journal.close()


@pytest.mark.parametrize("mutation", ["raw", "request", "status", "result", "audit_pin"])
def test_validation_reconstructs_instead_of_trusting_self_report(
    tmp_path: Path, mutation: str
) -> None:
    prepared, result, snapshot, _, _ = run_case(tmp_path)
    original_audit, original_result = snapshot.sha256, result.sha256
    if mutation == "raw":
        changed = replace(snapshot.attempts[0], raw="invented", raw_sha=digest("invented"))
        snapshot = replace(snapshot, attempts=(changed,))
    elif mutation == "request":
        changed = replace(snapshot.attempts[0], request="invented", request_sha=digest("invented"))
        snapshot = replace(snapshot, attempts=(changed,))
    elif mutation == "status":
        snapshot = replace(
            snapshot, attempts=(replace(snapshot.attempts[0], status="unknown_outcome"),)
        )
    elif mutation == "result":
        records = (
            result.records[0].model_copy(update={"response_received": False}),
            *result.records[1:],
        )
        result = replace(result, records=records)
        original_result = (
            result.sha256
        )  # even freshly hashed normalized output must match saved raw
    else:
        original_audit = None
    with pytest.raises(ValueError):
        runtime.validate(
            prepared,
            result,
            snapshot,
            expected_audit_sha=original_audit,
            expected_result_sha=original_result,
        )


@pytest.mark.parametrize("kind", runtime.RELATION_TYPES)
@pytest.mark.parametrize("decision", ["present", "absent", "unresolved"])
def test_all_eight_relation_protocols_only_not_semantic_acceptance(
    tmp_path: Path, kind: str, decision: str
) -> None:
    prepared, result, snapshot, _, _ = run_case(tmp_path)
    ids = tuple(r.item.item_id for r in result.records)
    relation = runtime.prepare_relations(
        prepared, result, snapshot, ((ids[0], ids[1], kind),), expected_audit_sha=snapshot.sha256
    )
    request = json.loads(runtime.requests(relation)[0][1])
    assert len(request["endpoint_items"]) == 2
    assert request["obligations"][0]["from_item"] == ids[0]
    journal = AuditJournal.create(
        tmp_path / "relations.sqlite", OfflineGrant(relation.prepared_id, max_calls=1)
    )
    rel_result = runtime.execute(relation, FakeAdapter(decision=decision), journal)
    rel_snapshot = journal.snapshot()
    journal.close()
    report = runtime.validate(
        relation,
        rel_result,
        rel_snapshot,
        expected_audit_sha=rel_snapshot.sha256,
        expected_result_sha=rel_result.sha256,
    )
    assert rel_result.relations[0].decision == decision
    assert report.semantic_status == "not_evaluated" and not report.budget_authorized


@pytest.mark.parametrize(
    "mutation", ["missing", "self", "type", "duplicate", "relation_endpoint", "relation_provenance"]
)
def test_relation_negative_controls(tmp_path: Path, mutation: str) -> None:
    prepared, result, snapshot, _, _ = run_case(tmp_path)
    ids = tuple(r.item.item_id for r in result.records)
    pairs = ((ids[0], ids[1], "supports"),)
    if mutation == "missing":
        pairs = (("missing", ids[1], "supports"),)
    elif mutation == "self":
        pairs = ((ids[0], ids[0], "supports"),)
    elif mutation == "type":
        pairs = ((ids[0], ids[1], "invented"),)
    elif mutation == "duplicate":
        pairs *= 2
    if mutation in ("missing", "self", "type", "duplicate"):
        with pytest.raises(ValueError):
            runtime.prepare_relations(
                prepared, result, snapshot, pairs, expected_audit_sha=snapshot.sha256
            )
        return
    relation = runtime.prepare_relations(
        prepared, result, snapshot, pairs, expected_audit_sha=snapshot.sha256
    )
    _, rel_result, _, report, _ = run_case(tmp_path / "child", relation, mutation)
    assert rel_result.errors and not report.protocol_complete


def test_journal_is_private_and_never_overwritten(tmp_path: Path) -> None:
    path, grant = tmp_path / "private.sqlite", OfflineGrant("plan")
    journal = AuditJournal.create(path, grant)
    journal.close()
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        AuditJournal.create(path, grant)
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        AuditJournal.open(path, replace(grant, max_calls=1))


@pytest.mark.parametrize(
    "actual",
    [
        {"old": "changed", "new": "n"},
        {"new": "n"},
        {"old": "o", "new": "n", "unexpected": "x"},
        {"old": "o"},
    ],
)
def test_additions_guard_negative_controls(actual: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        check_inventory({"old": "o"}, actual, {"new"})


def test_additions_guard_positive() -> None:
    check_inventory({"old": "o"}, {"old": "o", "new": "n"}, {"new"})


def test_pure_prepare_and_validate_have_no_implicit_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins
    import socket

    prepared, result, snapshot, _, _ = run_case(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("implicit I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(socket.socket, "connect", forbidden)
        again = fixture()
        assert again == prepared
        runtime.execute(again)
        report = runtime.validate(
            prepared,
            result,
            snapshot,
            expected_audit_sha=snapshot.sha256,
            expected_result_sha=result.sha256,
        )
        assert report.audit_verified


def test_saved_raw_replay_adapter_uses_same_execution_interface(tmp_path: Path) -> None:
    prepared, original, snapshot, _, _ = run_case(tmp_path)
    adapter = runtime.ReplayAdapter(tuple((a.request_sha, a.raw) for a in snapshot.attempts))
    journal = AuditJournal.create(tmp_path / "replay.sqlite", snapshot.grant)
    result = runtime.execute(prepared, adapter, journal)
    assert result.records == original.records
    assert journal.snapshot().attempts[0].adapter_mode == "replay"
    journal.close()


def test_full_runtime_to_frozen_evaluator_interface(tmp_path: Path) -> None:
    import r2_evaluation_v1 as ev

    prepared, result, snapshot, _, _ = run_case(tmp_path)
    source, plan, output = project(
        prepared,
        result,
        snapshot,
        expected_audit_sha=snapshot.sha256,
        expected_result_sha=result.sha256,
    )
    # Independent synthetic annotation, not copied from predicted field values.
    expected = (
        ("semantic_type", "forecast"),
        ("speaker_ref", None),
        ("perspective", "source_explicit"),
        ("speech_role", "statement"),
        ("polarity", "affirmed"),
        ("behavior_status", None),
        ("temporal_frame", None),
        ("value", None),
        ("unit", None),
        ("statement_role", "claim"),
    )
    gold = ev.Gold(
        version="synthetic-p2b",
        source_binding=ev.source_binding(source),
        atomic_denominator_approved=True,
        targets=tuple(
            ev.Target(
                target_id=f"target-{i}", evidence_span_ids=(o.focus.span_id,), fields=expected
            )
            for i, o in enumerate(plan.obligations)
        ),
    )
    reviews = ev.Reviews(
        source_binding=ev.source_binding(source),
        plan_id=plan.plan_id,
        contract_sha256=ev.CONTRACT_SHA,
        gold_sha256=ev.model_hash(gold),
        result_sha256=ev.model_hash(output),
        decisions=tuple(
            ev.Decision(
                record_sha256=ev.model_hash(row),
                reviewer_id="synthetic-oracle",
                reviewer_kind="synthetic_fixture",
                status="approved",
                reviewed_at="fixture",
                reason="literal faithful synthetic forecasts",
                target_id=f"target-{i}",
                fidelity="faithful",
                atomicity="single",
                constraints_retained=True,
                no_supported_item_confirmed=False,
                critical_errors=(),
            )
            for i, row in enumerate(output.records)
        ),
    )
    pins = ev.Pins(
        "synthetic-p2b",
        "company",
        "synthetic",
        ev.source_binding(source),
        plan.plan_id,
        ev.model_hash(output),
        ev.model_hash(gold),
        ev.model_hash(reviews),
        ev.CONTRACT_SHA,
        ev.POLICY_SHA256,
    )
    report = ev.evaluate(source, plan, output, gold, reviews, pins)
    assert report.local_item_gates_passed and not report.budget_authorized


@pytest.mark.parametrize("suite", ["core", "platform", "isolation"])
def test_guard_installed_before_test_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suite: str
) -> None:
    events = []
    monkeypatch.setattr(p2b_guard, "verify", lambda: {})
    monkeypatch.setattr(p2b_guard.p0, "block_external", lambda: events.append("blocked"))
    # Do not alter this pytest process's import policy; poison checks use a stub.
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path))
    monkeypatch.setattr(
        sys,
        "modules",
        {k: v for k, v in sys.modules.items() if not k.startswith("plugins.corpus._r2_")},
    )
    import builtins

    original = builtins.__import__

    def controlled_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("plugins.corpus._r2_") or name == "plugins.corpus.material_semantics":
            raise ImportError("poison control")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled_import)

    def suite_stub(name: str, output: Path) -> int:
        assert events == ["blocked"]
        events.append("collected")
        return 0

    monkeypatch.setattr(p2b_guard.p0, "suite", suite_stub)
    monkeypatch.setattr(
        sys, "argv", ["guard", "suite", "--suite", suite, "--out", str(tmp_path / "result.json")]
    )
    assert p2b_guard.main() == 0
    assert events == ["blocked", "collected"]


def test_total_receipt_storage_failure_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = fixture(tuple(f"公司{i}预计增产。" for i in range(9)))
    journal = AuditJournal.create(
        tmp_path / "audit.sqlite", OfflineGrant(prepared.prepared_id, max_calls=2)
    )
    adapter = FakeAdapter()

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("storage unavailable")

    monkeypatch.setattr(journal, "received", fail)
    monkeypatch.setattr(journal, "failed", fail)
    with pytest.raises(OSError):
        runtime.execute(prepared, adapter, journal)
    assert adapter.calls == 1
    assert journal.snapshot().attempts[0].status == "reserved"
    resumed = FakeAdapter()
    runtime.execute(prepared, resumed, journal)
    assert resumed.calls == 0
    journal.close()


def test_budget_exhaustion_retains_deferred_denominator(tmp_path: Path) -> None:
    prepared = fixture(tuple(f"公司{i}预计增产。" for i in range(9)))
    journal = AuditJournal.create(
        tmp_path / "audit.sqlite", OfflineGrant(prepared.prepared_id, max_calls=1)
    )
    adapter = FakeAdapter()
    result = runtime.execute(prepared, adapter, journal)
    snapshot = journal.snapshot()
    journal.close()
    assert adapter.calls == 1 and len(result.records) == 9
    assert result.records[-1].terminal == "deferred"
    report = runtime.validate(
        prepared,
        result,
        snapshot,
        expected_audit_sha=snapshot.sha256,
        expected_result_sha=result.sha256,
    )
    assert not report.protocol_complete


def test_fabricated_text_rehashed_result_cannot_override_raw(tmp_path: Path) -> None:
    prepared, result, snapshot, _, _ = run_case(tmp_path)
    record = result.records[0]
    assert record.item is not None
    bad = record.model_copy(
        update={"item": record.item.model_copy(update={"text": "invented content"})}
    )
    altered = replace(result, records=(bad, *result.records[1:]))
    with pytest.raises(ValueError, match="reconstructed"):
        project(
            prepared,
            altered,
            snapshot,
            expected_audit_sha=snapshot.sha256,
            expected_result_sha=altered.sha256,
        )
