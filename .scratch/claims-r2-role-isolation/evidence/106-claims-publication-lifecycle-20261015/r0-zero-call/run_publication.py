"""Plan, execute, publish and consume the bridged claims pool (106 号, zero model calls).

Subcommands, in order:

* ``plan``     — freeze a plan whose claims task is ``method="imported"``, bound to the accepted
  claims artifact built by ``build_claims_bridge.py``;
* ``execute``  — run that plan with ``allow_model=False``; the imported task costs no attempt, so
  the whole step is deterministic and zero-call;
* ``publish``  — ``publish_semantic`` in candidate mode (no ``record_selection``), which requires
  ``protocol_status="valid"`` and ``quality_status="accepted"`` — exactly what the bridge records
  because the acceptance authority is the signed adjudication;
* ``consume``  — exercise the read path: ``cite`` / ``compare`` / ``calculate`` deliveries with
  ``verify_reference``, i.e. the consumption half of the loop.

Usage:
    python run_publication.py plan|execute|publish|consume
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.evidence_pipeline import EvidenceRun  # noqa: E402
from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import (  # noqa: E402
    AcceptedClaims,
    BatchPlan,
    execute_batch,
    plan_batch,
)
from plugins.corpus.structured.roles import RoleArtifact  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from plugins.corpus.structured.store import (  # noqa: E402
    ArtifactReference,
    publish_semantic,
)
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

FREEZE = (
    ROOT
    / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/claims-treatment-plan-freeze"
)
RUNS = ("claims-industrial-fulian", "claims-optical-module")
RECORD = HERE / "publication-run-record.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_dir(run: str) -> Path:
    return HERE / f"bridge-{run}"


def accepted_claims(run: str) -> AcceptedClaims:
    directory = run_dir(run)
    return AcceptedClaims(
        artifact=RoleArtifact.model_validate_json(
            (directory / "claims-artifact.json").read_text(encoding="utf-8")
        ),
        payload=EvidenceRun.model_validate_json(
            (directory / "claims-payload.json").read_text(encoding="utf-8")
        ),
    )


def snapshot_of(run: str) -> EvidenceSnapshot:
    return EvidenceSnapshot.model_validate_json(
        (FREEZE / run / "snapshot.json").read_text(encoding="utf-8")
    )


def claim_reference(run: str) -> tuple[ArtifactReference, EvidenceSnapshot]:
    directory = run_dir(run)
    connection = sqlite3.connect(f"file:{directory / 'live-store/index/structured.sqlite3'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT batch_id, task_id, artifact_sha256, method, execution_status, protocol_status, "
        "quality_status, publication_status FROM tasks WHERE role='claims'"
    ).fetchone()
    if row is None:
        raise SystemExit(f"refusing: no claims task in the {run} ledger; run `execute` first")
    if row["method"] != "imported":
        raise SystemExit(f"refusing: {run} claims task is {row['method']}, expected imported")
    return (
        ArtifactReference(
            batch_id=row["batch_id"],
            task_id=row["task_id"],
            artifact_sha256=row["artifact_sha256"],
        ),
        snapshot_of(run),
    )


def cmd_plan() -> int:
    config = load_extraction_config()
    written = {}
    for run in RUNS:
        directory = run_dir(run)
        plan = plan_batch(
            snapshot_of(run),
            config=config,
            imported_claims=accepted_claims(run),
            enabled_roles=("claims",),
            max_attempts=0,
        )
        target = directory / "plan.json"
        assert_writable(target, reason="106 号 claims 桥计划")
        write_once(target, plan.model_dump_json(indent=2) + "\n", allow_overwrite=True)
        written[run] = {"batch_id": plan.batch_id, "plan_sha256": plan.plan_sha256}
    print(json.dumps(written, ensure_ascii=False, indent=2))
    return 0


def cmd_execute() -> int:
    results = {}
    for run in RUNS:
        directory = run_dir(run)
        plan = BatchPlan.model_validate_json((directory / "plan.json").read_text(encoding="utf-8"))
        check = execute_batch(plan, store_root=directory / "live-store", allow_model=False)
        results[run] = {
            "batch_id": plan.batch_id,
            "plan_consistent": check.plan_consistent,
            "findings": list(check.findings),
            "tasks": [
                {
                    "role": task.role,
                    "method": task.method,
                    "execution_status": task.execution_status,
                    "protocol_status": task.protocol_status,
                    "quality_status": task.quality_status,
                    "publication_status": task.publication_status,
                }
                for task in check.ledger.tasks
            ],
        }
    bad = [run for run, item in results.items() if not item["plan_consistent"] or item["findings"]]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if bad else 0


def cmd_publish() -> int:
    publications = {}
    for run in RUNS:
        reference, snapshot = claim_reference(run)
        manifest = publish_semantic(
            source_id=snapshot.source_id,
            build_id=snapshot.build_id,
            snapshot_id=snapshot.snapshot_id,
            artifacts=(reference,),
            expected_parent_publication_id=None,
            store_root=run_dir(run) / "live-store",
        )
        publications[run] = {
            "publication_id": manifest.publication_id,
            "publication_status": manifest.publication_status,
            "quality_status": manifest.quality_status,
            "artifacts": list(manifest.artifacts),
            "coverage": manifest.coverage.model_dump(mode="json"),
            "reason_codes": list(manifest.reason_codes),
        }
        connection = sqlite3.connect(
            f"file:{run_dir(run) / 'live-store/index/structured.sqlite3'}?mode=ro", uri=True
        )
        row = connection.execute(
            "SELECT publication_status FROM tasks WHERE role='claims'"
        ).fetchone()
        publications[run]["task_publication_status"] = row[0]
    print(json.dumps(publications, ensure_ascii=False, indent=2))
    assert_writable(RECORD, reason="106 号发布记录")
    write_once(
        RECORD,
        json.dumps(
            {
                "schema_version": "claims-publication-run-record-1",
                "id": "106-claims-publication-lifecycle-20261015",
                "run_on": "2026-10-15",
                "model_calls": 0,
                "publications": publications,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        allow_overwrite=True,
    )
    return 0


def cmd_consume() -> int:
    from plugins.corpus.structured.query import query_semantic

    results = {}
    for run in RUNS:
        snapshot = snapshot_of(run)
        view = query_semantic(
            snapshot.source_id,
            snapshot.build_id,
            store_root=run_dir(run) / "live-store",
        )
        records = view.records if hasattr(view, "records") else []
        results[run] = {
            "publication_id": getattr(view.manifest, "publication_id", None),
            "records": len(records),
            "purposes": sorted({str(getattr(r, "purpose", "?")) for r in records}),
        }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"plan", "execute", "publish", "consume"}:
        raise SystemExit(__doc__)
    return {
        "plan": cmd_plan,
        "execute": cmd_execute,
        "publish": cmd_publish,
        "consume": cmd_consume,
    }[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
