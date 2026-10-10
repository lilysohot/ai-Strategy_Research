"""Verify Issue 25 differs from Issue 22 only by protocol and derived identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plugins.corpus.structured.ledger import BatchPlan

HERE = Path(__file__).resolve().parent
ISSUE22 = HERE.parents[1] / "22-doubao-lite-provider-ceiling-20261010" / "p0-256k-minimal-live"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    old = BatchPlan.model_validate_json((ISSUE22 / "plan.json").read_text(encoding="utf-8"))
    new = BatchPlan.model_validate_json((HERE / "plan.json").read_text(encoding="utf-8"))
    old.verify_identity()
    new.verify_identity()
    if old.snapshot != new.snapshot:
        raise RuntimeError("snapshot changed")
    if old.imported_material_items != new.imported_material_items:
        raise RuntimeError("accepted items changed")
    if old.max_attempts != new.max_attempts or old.role_max_attempts != new.role_max_attempts:
        raise RuntimeError("attempt budget changed")
    if old.enabled_roles != new.enabled_roles or old.relations != new.relations:
        raise RuntimeError("relation scope changed")
    old_profiles = {profile.role: profile for profile in old.profiles}
    new_profiles = {profile.role: profile for profile in new.profiles}
    for role in ("claims", "material_items"):
        if old_profiles[role] != new_profiles[role]:
            raise RuntimeError(f"unrelated profile changed: {role}")
    old_relation = old_profiles["material_relations"]
    new_relation = new_profiles["material_relations"]
    if old_relation.model_dump(exclude={"protocol", "role_profile_sha256"}) != (
        new_relation.model_dump(exclude={"protocol", "role_profile_sha256"})
    ):
        raise RuntimeError("relation profile changed beyond protocol")
    if old_relation.protocol != "material-relations-question-group-jsonl-v1":
        raise RuntimeError("Issue 22 baseline protocol drifted")
    if new_relation.protocol != "material-relations-question-group-jsonl-v2":
        raise RuntimeError("Issue 25 did not freeze boolean v2")
    manifest = json.loads((HERE / "freeze-manifest.json").read_text(encoding="utf-8"))
    if manifest["files_sha256"]["plan.json"] != _sha256(HERE / "plan.json"):
        raise RuntimeError("frozen plan bytes drifted")
    if manifest["files_sha256"]["final-gate.json"] != _sha256(HERE / "final-gate.json"):
        raise RuntimeError("frozen gate bytes drifted")
    summary = {
        "schema_version": "issue25-final-live-plan-diff-1",
        "status": "verified_authorized_not_executed",
        "baseline_batch_id": old.batch_id,
        "new_batch_id": new.batch_id,
        "new_plan_sha256": new.plan_sha256,
        "unchanged": {
            "snapshot_id": new.snapshot.snapshot_id,
            "accepted_items": True,
            "candidate_rule": new.relations.rule_version,
            "items_validation": new.relations.items_validation_version,
            "dependency_policy": new.relations.dependency_policy,
            "provider": new_relation.provider,
            "model": new_relation.model,
            "request_options": new_relation.request_options,
            "relation_attempts_max": new.role_max_attempts["material_relations"],
        },
        "changed": {"protocol": {"from": old_relation.protocol, "to": new_relation.protocol}},
        "model_requests_during_verification": 0,
        "execution_authorized": True,
        "publication_authorized": False,
    }
    (HERE / "plan-diff-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
