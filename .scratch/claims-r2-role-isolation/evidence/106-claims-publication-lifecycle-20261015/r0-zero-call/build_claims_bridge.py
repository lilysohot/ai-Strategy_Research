"""Build the claims bridge inputs (106 号, zero model calls).

Turns the xyl-signed treatment adjudications into the two files the new ledger bridge consumes:

* ``claims-payload.json`` — the ``EvidenceRun`` reduced to the **adjudicated-accepted** facts
  (``matched`` + ``correct_extra`` only; ``incorrect`` and ``duplicate`` are dropped by the
  adjudication itself, never silently — the drop ledger is written out);
* ``claims-artifact.json`` — the upstream ``RoleArtifact`` that declares this run accepted.

Why the artifact may declare ``quality_status="accepted"``: the acceptance authority here is the
signed human adjudication, not a machine protocol check — exactly the semantics of the pre-existing
items bridge (``_import_material_items_execution``), which also enters the ledger as
``protocol_status="valid"`` / ``quality_status="accepted"``. Nothing here invents a judgement:
payload identity is the canonical hash of the reduced run, and every dropped fact is listed.

Usage:
    python build_claims_bridge.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.evidence_pipeline import EvidenceRun, fingerprint  # noqa: E402
from plugins.corpus.structured.config import canonical_hash  # noqa: E402
from plugins.corpus.structured.roles import RoleArtifact, RoleCoverage  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

FREEZE = (
    ROOT
    / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/claims-treatment-plan-freeze"
)
SIGNED = (
    ROOT
    / "evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication"
    / "candidate-adjudications.signed.json"
)
RUNS = ("claims-industrial-fulian", "claims-optical-module")
KEPT_JUDGEMENTS = ("matched", "correct_extra")
DROP_REASONS = {
    "incorrect": "adjudicated_incorrect",
    "duplicate": "adjudicated_duplicate",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_run(run: str, adjudications: list[dict[str, Any]]) -> dict[str, Any]:
    run_dir = FREEZE / run
    snapshot = EvidenceSnapshot.model_validate_json((run_dir / "snapshot.json").read_text())
    plan = load(run_dir / "plan.json")
    task = next(task for task in plan["tasks"] if task["role"] == "claims")
    protocol = task["protocol"]

    import sqlite3

    connection = sqlite3.connect(f"file:{run_dir / 'live-store/index/structured.sqlite3'}?mode=ro", uri=True)
    digest = connection.execute("SELECT payload_object_sha256 FROM tasks").fetchone()[0]
    raw = (
        run_dir
        / "live-store/objects/sha256"
        / digest.removeprefix("sha256:")[:2]
        / f"{digest.removeprefix('sha256:')}.json"
    )
    payload = EvidenceRun.model_validate(load(raw))

    verdict = {row["candidate_id"]: str(row["judgement"]) for row in adjudications}
    licensed = {row["candidate_id"]: tuple(row["usable_for"]) for row in adjudications}
    if any(set(value) - {"cite", "compare", "calculate"} for value in licensed.values()):
        raise SystemExit("refusing: worksheet carries a purpose outside the frozen vocabulary")
    dropped = {
        fact.fact_id: DROP_REASONS[verdict[fact.fact_id]]
        for fact in payload.facts
        if verdict.get(fact.fact_id) not in KEPT_JUDGEMENTS
    }
    if len(dropped) + sum(
        1 for fact in payload.facts if verdict.get(fact.fact_id) in KEPT_JUDGEMENTS
    ) != len(payload.facts):
        raise SystemExit(f"refusing: adjudication does not cover every fact in {run}")

    # Backfill (U decision A, 2026-10-15): the signed adjudication is the authority, so an accepted
    # fact carries quality "ok", and its purposes are the ones the *signed* claim_use_axes rule
    # already computed (worksheet `usable_for`), not the extraction-side label. Every override is
    # recorded — including extraction-side "rejected" rows the adjudication accepted.
    overrides: dict[str, dict[str, str]] = {}
    kept: list[Any] = []
    for fact in payload.facts:
        if verdict.get(fact.fact_id) not in KEPT_JUDGEMENTS:
            continue
        before_quality = str(fact.claim.quality_status)
        before_uses = tuple(fact.usable_for)
        after_uses = licensed[fact.fact_id]
        if before_quality != "ok" or before_uses != after_uses:
            overrides[fact.fact_id] = {
                "quality_before": before_quality,
                "quality_after": "ok",
                "usable_for_before": ",".join(before_uses) or "(none)",
                "usable_for_after": ",".join(after_uses) or "(none)",
                "judgement": verdict[fact.fact_id],
            }
        kept.append(
            fact.model_copy(
                update={
                    "usable_for": after_uses,
                    "claim": replace(fact.claim, quality_status="ok"),
                }
            )
        )
    # run_id is the content fingerprint of the run: dropping adjudicated facts changes it, so the
    # accepted run must carry a freshly computed identity (never a borrowed one).
    reduced = payload.model_copy(update={"facts": tuple(kept)})
    accepted_run = reduced.model_copy(
        update={
            "run_id": fingerprint(
                reduced.model_dump(mode="json", exclude={"run_id"})  # type: ignore[arg-type]
            )
        }
    )
    accepted_run.verify_identity()

    base = RoleArtifact(
        artifact_id="sha256:" + "0" * 64,
        role="claims",
        snapshot_id=snapshot.snapshot_id,
        task_id=task["task_id"],
        protocol=protocol,
        business_contract="EvidenceRun/EvidenceFact",
        payload_sha256=canonical_hash(accepted_run.model_dump(mode="json")),
        payload_media_type="application/json",
        upstream_artifact_ids=(),
        coverage=RoleCoverage(
            scoped_unit_ids=tuple(task["scoped_unit_ids"]),
            omitted_unit_ids=(),
            reason_codes=(
                "xyl_signed_adjudication_2026_10_15",
                "adjudicated_facts_only",
            ),
        ),
        execution_status="succeeded",
        protocol_status="valid",
        context_status="complete",
        quality_status="accepted",
    )
    artifact = base.model_copy(
        update={
            "artifact_id": canonical_hash(base.model_dump(mode="json", exclude={"artifact_id"}))
        }
    )
    artifact.verify_identity()
    return {
        "run": run,
        "snapshot_id": snapshot.snapshot_id,
        "source_id": snapshot.source_id,
        "build_id": snapshot.build_id,
        "protocol": protocol,
        "task_id": task["task_id"],
        "kept": len(kept),
        "dropped": len(dropped),
        "dropped_reasons": dropped,
        "facts_before": len(payload.facts),
        "quality_overrides": len(overrides),
        "overrides": overrides,
        "usable_for_after": {
            ",".join(fact.usable_for) or "(none)": sum(
                1 for kept_fact in kept if tuple(kept_fact.usable_for) == tuple(fact.usable_for)
            )
            for fact in kept
        },
        "artifact": json.loads(artifact.model_dump_json()),
        "payload": json.loads(accepted_run.model_dump_json()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    adjudications = load(SIGNED)["adjudications"]
    results = [build_run(run, adjudications) for run in RUNS]

    outputs: dict[Path, str] = {}
    ledger = []
    for result in results:
        directory = HERE / f"bridge-{result['run']}"
        outputs[directory / "claims-artifact.json"] = (
            json.dumps(result["artifact"], ensure_ascii=False, indent=2) + "\n"
        )
        outputs[directory / "claims-payload.json"] = (
            json.dumps(result["payload"], ensure_ascii=False, indent=2) + "\n"
        )
        ledger.append(
            {
                "run": result["run"],
                "snapshot_id": result["snapshot_id"],
                "source_id": result["source_id"],
                "protocol": result["protocol"],
                "facts_before": result["facts_before"],
                "kept": result["kept"],
                "dropped": result["dropped"],
                "dropped_reasons": result["dropped_reasons"],
                "backfill": {
                    "decision": "U 裁定 A（2026-10-15）：裁定接受 ⇒ quality=ok；用途取工作表按已签 claim_use_axes 规则算出的 usable_for",
                    "overrides": result["overrides"],
                    "override_count": result["quality_overrides"],
                    "usable_for_after": result["usable_for_after"],
                },
                "artifact_id": result["artifact"]["artifact_id"],
                "payload_sha256": result["artifact"]["payload_sha256"],
            }
        )

    record = {
        "schema_version": "claims-bridge-inputs-1",
        "id": "106-claims-publication-lifecycle-20261015",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "rule": "只导入 matched + correct_extra；incorrect / duplicate 由裁定本身剔除，逐条登记",
        "runs": ledger,
        "outputs": {str(path.relative_to(HERE)): hashlib.sha256(data.encode()).hexdigest() for path, data in outputs.items()},
    }
    outputs[HERE / "bridge-inputs-record.json"] = (
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )

    if args.no_write:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    for path, data in outputs.items():
        assert_writable(path, reason="106 号 claims 桥输入工件")
        if path.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite {path.name}; use --force")
        write_once(path, data, allow_overwrite=True)
    print(json.dumps(record["runs"], ensure_ascii=False, indent=2))
    print(f"wrote {len(outputs)} files under {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
