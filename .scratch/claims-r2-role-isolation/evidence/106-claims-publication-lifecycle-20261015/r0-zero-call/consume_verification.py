"""Consume the published claims pool through all three purposes (106 号, zero model calls).

For each published run and each purpose — ``cite``, ``compare``, ``calculate`` — take one record the
publication actually licences (``purpose ∈ usable_for``), build the frozen report reference from it,
and run the read-only ``verify_reference`` audit. A purpose with no licensed record is reported, not
skipped silently.

This is the consumption half of the loop: publication alone proves nothing until a report reference
survives verification.

Usage:
    python consume_verification.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured.consumption import (  # noqa: E402
    SemanticConsumption,
    SemanticReceipt,
    reference_for_record,
    verify_reference,
)
from plugins.corpus.structured.query import Purpose, query_semantic  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

FREEZE = (
    ROOT
    / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/claims-treatment-plan-freeze"
)
RUNS = ("claims-industrial-fulian", "claims-optical-module")
PURPOSES: tuple[Purpose, ...] = ("cite", "compare", "calculate")
RECORD = HERE / "consumption-verification-record.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_dir(run: str) -> Path:
    return HERE / f"bridge-{run}"


def snapshot_of(run: str) -> EvidenceSnapshot:
    return EvidenceSnapshot.model_validate_json(
        (FREEZE / run / "snapshot.json").read_text(encoding="utf-8")
    )


def consume(run: str) -> dict[str, Any]:
    root = run_dir(run) / "live-store"
    snapshot = snapshot_of(run)
    os.environ["CORPUS_STRUCTURED_ROOT"] = str(root)
    results: dict[str, Any] = {}
    for purpose in PURPOSES:
        page = query_semantic(
            snapshot.source_id,
            snapshot.build_id,
            purpose=purpose,
            query_text="",
            store_root=root,
        )
        licensed = [r for r in page.records if purpose in r.usable_for]
        if not licensed:
            results[purpose] = {
                "status": "no_licensed_record",
                "records_in_page": len(page.records),
                "page_status": page.page_status,
                "note": "该用途在此发布中没有被许可的记录（usable_for 不含该用途）",
            }
            continue
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
        _verified, problems = verify_reference(
            ref, consumption, final_text=quote, pending_aware=False
        )
        results[purpose] = {
            "status": "verified" if not problems else "problems",
            "publication_id": page.publication_id,
            "record_id": record.record_id,
            "licensed_records": len(licensed),
            "context_status": record.context_status,
            "quality_status": record.quality_status,
            "dependency_kinds": sorted({d.kind for d in record.dependencies}),
            "problems": problems,
        }
    return results


def main() -> int:
    results = {run: consume(run) for run in RUNS}
    failed = [
        f"{run}/{purpose}"
        for run, item in results.items()
        for purpose, entry in item.items()
        if entry["status"] != "verified"
    ]
    record = {
        "schema_version": "claims-consumption-verification-1",
        "id": "106-claims-publication-lifecycle-20261015",
        "run_on": "2026-10-15",
        "model_calls": 0,
        "rule": "三用途各取一条发布许可的记录，经 verify_reference 只读审计；无许可记录如实登记",
        "runs": results,
        "verdict": {
            "all_verified": not failed,
            "not_verified": failed,
        },
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    assert_writable(RECORD, reason="106 号消费验收记录")
    write_once(RECORD, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
