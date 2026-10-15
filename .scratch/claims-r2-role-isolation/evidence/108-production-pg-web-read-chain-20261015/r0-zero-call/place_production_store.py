"""Place the two signed claims publications into a merged production store (108 号 S1, zero model calls).

Replays the 106 号 bridge inputs (claims-artifact.json + claims-payload.json, both runs)
through plan_batch → execute_batch → publish_semantic against a *target* store root.
The ledger bridge semantics are the ones signed in 106 号: the human-signed adjudication
is the authority, so an imported task enters as protocol_status=valid /
quality_status=accepted with zero model calls.

Modes:
* ``--verify-only ROOT``  — replay into an existing (empty) root and print publication ids
  for comparison against the 106 号 signed record; refuses if the root already has objects.
* ``--place ROOT``        — same replay, then assert every publication id equals the signed
  106 号 value before printing the final summary. Refuses to touch a non-empty root.

Usage:
    uv run python place_production_store.py --verify-only /tmp/scratch-root
    uv run python place_production_store.py --place /abs/path/data/corpus/structured-store
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import (  # noqa: E402
    AcceptedClaims,
    BatchPlan,
    execute_batch,
    plan_batch,
)
from plugins.corpus.structured.roles import RoleArtifact  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from plugins.corpus.structured.store import ArtifactReference, publish_semantic  # noqa: E402

FREEZE = (
    ROOT
    / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/claims-treatment-plan-freeze"
)
# 桥输入是 106 号已签落地的产物，本脚本只读、逐字不动
BASE_106 = (
    ROOT / "evidence/106-claims-publication-lifecycle-20261015/r0-zero-call"
)
RUNS = ("claims-industrial-fulian", "claims-optical-module")

# 106 号 signed publication ids（landing-record.json「S2_execute_and_publish.publications」）
SIGNED_PUBLICATION_IDS = {
    "claims-industrial-fulian": "sha256:5fc7116b",
    "claims-optical-module": "sha256:8dde446f",
}
SIGNED_PREFIX_LEN = len("sha256:") + 8  # match on the 8-hex abbreviation used in records


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_claims(run: str) -> AcceptedClaims:
    from plugins.corpus.evidence_pipeline import EvidenceRun

    directory = BASE_106 / f"bridge-{run}"
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


def ensure_empty(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"refusing: target store root is not empty: {root}")


def replay(store_root: Path) -> dict[str, dict[str, object]]:
    config = load_extraction_config()
    ensure_empty(store_root)
    store_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, object]] = {}
    for run in RUNS:
        snapshot = snapshot_of(run)
        plan: BatchPlan = plan_batch(
            snapshot,
            config=config,
            imported_claims=accepted_claims(run),
            enabled_roles=("claims",),
            max_attempts=0,
        )
        check = execute_batch(plan, store_root=store_root, allow_model=False)
        if not check.plan_consistent or check.findings:
            raise SystemExit(
                f"refusing: {run} execution inconsistent: findings={list(check.findings)}"
            )
        claims_task = next(t for t in check.ledger.tasks if t.role == "claims")
        if claims_task.method != "imported":
            raise SystemExit(f"refusing: {run} claims task method={claims_task.method}")
        if claims_task.protocol_status != "valid" or claims_task.quality_status != "accepted":
            raise SystemExit(
                f"refusing: {run} claims task protocol={claims_task.protocol_status} "
                f"quality={claims_task.quality_status}; the signed-bridge semantics broke"
            )
        manifest = publish_semantic(
            source_id=snapshot.source_id,
            build_id=snapshot.build_id,
            snapshot_id=snapshot.snapshot_id,
            artifacts=(
                ArtifactReference(
                    batch_id=plan.batch_id,
                    task_id=claims_task.task_id,
                    artifact_sha256=claims_task.artifact_sha256,
                ),
            ),
            expected_parent_publication_id=None,
            store_root=store_root,
        )
        results[run] = {
            "publication_id": manifest.publication_id,
            "publication_status": manifest.publication_status,
            "quality_status": manifest.quality_status,
            "batch_id": plan.batch_id,
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", dest="verify_only", default=None)
    parser.add_argument("--place", dest="place", default=None)
    args = parser.parse_args()
    root_arg = args.verify_only or args.place
    if not root_arg or (args.verify_only and args.place):
        raise SystemExit("usage: --verify-only ROOT | --place ROOT")

    root = Path(root_arg).resolve()
    results = replay(root)
    print(json.dumps(results, ensure_ascii=False, indent=2))

    if args.place:
        mismatches = {}
        for run, item in results.items():
            signed = SIGNED_PUBLICATION_IDS[run]
            got = str(item["publication_id"])
            if got[:SIGNED_PREFIX_LEN] != signed[:SIGNED_PREFIX_LEN]:
                mismatches[run] = {"signed": signed, "got": got}
        if mismatches:
            raise SystemExit(f"refusing: publication ids diverge from the signed 106 record: {mismatches}")
        print("place ok: publication ids match the signed 106 record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
