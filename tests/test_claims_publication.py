"""106-号 invariants: the claims treatment pool is bridged, published and consumable.

The 105-号 A-tier decision said "enter the publication/consumption loop". This pins what that means
in practice, so it cannot be claimed without being true:

* the bridge admits **only adjudication-accepted** facts (``matched`` + ``correct_extra``); every
  dropped fact is listed with its reason — the pool is never quietly trimmed;
* the backfill (U decision A, 2026-10-15) is the signed adjudication landing on the fact layer:
  accepted ⇒ ``quality_status="ok"``, purposes = the ones the *signed* ``claim_use_axes`` rule
  computed. Overrides are recorded, including the row the extractor labelled ``rejected``;
* publication happens through the real gate (candidate mode: valid + accepted), and the task ends
  ``published``;
* consumption works for **all three** purposes — a reference built from a licensed record survives
  ``verify_reference``. Publication alone proves nothing; this is the other half.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from plugins.corpus.evidence_pipeline import EvidenceRun
from plugins.corpus.structured.consumption import (
    SemanticConsumption,
    SemanticReceipt,
    reference_for_record,
    verify_reference,
)
from plugins.corpus.structured.query import query_semantic
from plugins.corpus.structured.snapshot import EvidenceSnapshot
from tools.check_claims_gate import sha256

SCRATCH = Path(__file__).resolve().parents[1] / ".scratch/claims-r2-role-isolation"
HERE = SCRATCH / "evidence/106-claims-publication-lifecycle-20261015/r0-zero-call"
FREEZE = SCRATCH / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/claims-treatment-plan-freeze"
WORKSHEET = (
    SCRATCH
    / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication"
    / "candidate-adjudications.signed.json"
)
RUNS = ("claims-industrial-fulian", "claims-optical-module")
PURPOSES = ("cite", "compare", "calculate")


def _payload(run: str) -> EvidenceRun:
    return EvidenceRun.model_validate_json(
        (HERE / f"bridge-{run}/claims-payload.json").read_text(encoding="utf-8")
    )


def _adjudications() -> list[dict]:
    return json.loads(WORKSHEET.read_text(encoding="utf-8"))["adjudications"]


def _task_row(run: str) -> sqlite3.Row:
    connection = sqlite3.connect(
        f"file:{HERE / f'bridge-{run}/live-store/index/structured.sqlite3'}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    return connection.execute("SELECT * FROM tasks WHERE role='claims'").fetchone()


def test_bridge_admits_only_adjudication_accepted_facts() -> None:
    verdict = {row["candidate_id"]: row["judgement"] for row in _adjudications()}
    total = 0
    for run in RUNS:
        payload = _payload(run)
        for fact in payload.facts:
            assert verdict[fact.fact_id] in {"matched", "correct_extra"}, (
                f"{fact.fact_id} was dropped by adjudication yet reached the published pool"
            )
        total += len(payload.facts)
    assert total == 84, "84 accepted facts (matched 20 + correct_extra 64)"
    record = json.loads((HERE / "bridge-inputs-record.json").read_text(encoding="utf-8"))
    dropped = sum(len(run["dropped_reasons"]) for run in record["runs"])
    assert dropped == 9, "9 dropped facts (incorrect 3 + duplicate 6) stay listed by reason"


def test_backfill_is_the_signed_adjudication_landing_on_the_fact_layer() -> None:
    licensed = {row["candidate_id"]: tuple(row["usable_for"]) for row in _adjudications()}
    purposes = Counter()
    for run in RUNS:
        for fact in _payload(run).facts:
            assert fact.claim.quality_status == "ok", "accepted facts carry the adjudicated quality"
            assert tuple(fact.usable_for) == licensed[fact.fact_id], (
                "purposes are the ones the signed claim_use_axes rule computed"
            )
            assert set(fact.usable_for) <= {"cite", "compare", "calculate"}
            purposes[tuple(fact.usable_for)] += 1
    assert purposes[("cite", "compare", "calculate")] == 10
    record = json.loads((HERE / "bridge-inputs-record.json").read_text(encoding="utf-8"))
    overrides = {k: v for run in record["runs"] for k, v in run["backfill"]["overrides"].items()}
    assert any(v["quality_before"] == "rejected" for v in overrides.values()), (
        "the extractor-labelled rejected row the adjudication accepted is recorded, not hidden"
    )


def test_publication_is_published_through_the_real_gate() -> None:
    for run in RUNS:
        row = _task_row(run)
        assert row["method"] == "imported", "bridged claims cost no model attempt"
        assert row["protocol_status"] == "valid"
        assert row["quality_status"] == "accepted"
        assert row["publication_status"] == "published"
        assert row["payload_object_sha256"]


def test_all_three_purposes_are_consumable(monkeypatch) -> None:
    for run in RUNS:
        root = HERE / f"bridge-{run}/live-store"
        # verify_reference re-reads the authoritative publication through the configured root.
        monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
        snapshot = EvidenceSnapshot.model_validate_json(
            (FREEZE / run / "snapshot.json").read_text(encoding="utf-8")
        )
        for purpose in PURPOSES:
            page = query_semantic(
                snapshot.source_id,
                snapshot.build_id,
                purpose=purpose,
                query_text="",
                store_root=root,
            )
            licensed = [r for r in page.records if purpose in r.usable_for]
            assert licensed, f"{run}/{purpose}: no licensed record in the published pool"
            record = licensed[0]
            quote = record.evidence[0].quote
            ref = reference_for_record(
                page.publication_id, record, purpose, report_anchor="C1", report_quote=quote
            )
            consumption = SemanticConsumption(
                receipts=[
                    SemanticReceipt(
                        source_id=snapshot.source_id,
                        build_id=snapshot.build_id,
                        call_id="call-1",
                        turn=1,
                        page=page,
                        statuses={record.record_id: "delivered"},
                    )
                ]
            )
            _, problems = verify_reference(ref, consumption, final_text=quote, pending_aware=False)
            assert problems == [], f"{run}/{purpose}: {problems}"


def test_frozen_records_are_untouched_by_the_publication_lifecycle() -> None:
    assert (
        sha256(SCRATCH / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/claims-treatment-run-record.json")
        == "6154292f59b71924cf293db655b42e1b39ac52282c4390d0a4e5bc073a3698ba"
    )
    assert (
        sha256(
            SCRATCH
            / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication"
            / "candidate-adjudications.signed.json"
        )
        == "d639e8a20d6ce0eef14fde1ace407eebb4fde7670e056b1adeabeb82deac75c2"
    )
    assert (
        sha256(
            SCRATCH
            / "evidence/104-claims-prereg-v4-amendment-20261014/r0-zero-call/claims-preregistration-v4.json"
        )
        == "6b5c93d582c9ff8cebfd5e35944a46951068de0e95685abff4645ed1cdaaa510"
    )
