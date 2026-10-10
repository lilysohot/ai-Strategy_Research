"""Verify the final P14 plan against P12 without issuing model requests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plugins.corpus.structured.ledger import BatchPlan

HERE = Path(__file__).resolve().parent
P12 = HERE.parent / "p12-relation-selector-v2-zero-call"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            nested_key for nested in value.values() for nested_key in _keys(nested)
        }
    if isinstance(value, list):
        return {nested_key for nested in value for nested_key in _keys(nested)}
    return set()


def main() -> None:
    old = BatchPlan.model_validate_json((P12 / "plan.json").read_text(encoding="utf-8"))
    new_path = HERE / "plan.json"
    new = BatchPlan.model_validate_json(new_path.read_text(encoding="utf-8"))
    old.verify_identity()
    new.verify_identity()
    if old.snapshot.snapshot_id != new.snapshot.snapshot_id:
        raise RuntimeError("snapshot changed")
    if old.imported_material_items != new.imported_material_items:
        raise RuntimeError("accepted items import changed")
    if old.max_attempts != new.max_attempts or old.role_max_attempts != new.role_max_attempts:
        raise RuntimeError("attempt budget changed")
    if old.enabled_roles != new.enabled_roles or old.relations != new.relations:
        raise RuntimeError("role or relation scope changed")

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
    if new_relation.protocol != "material-relations-question-group-jsonl-v1":
        raise RuntimeError("P14 did not freeze the question-group protocol")

    serialized = new_path.read_text(encoding="utf-8")
    raw_plan = json.loads(serialized)
    if "api_key" in _keys(raw_plan) or "bearer " in serialized.lower():
        raise RuntimeError("plan contains an inline credential field")
    if any(
        profile.credential_ref is None or not profile.credential_ref.startswith("env:")
        for profile in new.profiles
    ):
        raise RuntimeError("plan contains a non-reference credential binding")

    summary = {
        "schema_version": "relation-question-group-final-plan-diff-1",
        "status": "frozen_not_executed",
        "p12_batch_id": old.batch_id,
        "p14_batch_id": new.batch_id,
        "p14_plan_sha256": new.plan_sha256,
        "p14_plan_file_sha256": _sha256(new_path),
        "final_gate_sha256": _sha256(HERE / "final-gate.json"),
        "model_requests_during_freeze": 0,
        "unchanged": {
            "snapshot_id": new.snapshot.snapshot_id,
            "imported_items": True,
            "enabled_roles": list(new.enabled_roles),
            "max_attempts": new.max_attempts,
            "role_max_attempts": new.role_max_attempts,
            "relation_candidate_rule": new.relations.rule_version,
            "items_validation_version": new.relations.items_validation_version,
            "dependency_policy": new.relations.dependency_policy,
            "provider": new_relation.provider,
            "model": new_relation.model,
            "credential_reference_only": True,
        },
        "changed": {
            "material_relations_protocol": {
                "from": old_relation.protocol,
                "to": new_relation.protocol,
            }
        },
        "execution_authorized": False,
        "publication_authorized": False,
        "next_gate": "explicit authorization for at most four final question-group relation calls",
    }
    (HERE / "plan-diff-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
