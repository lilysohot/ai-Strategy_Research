"""Verify that the frozen P12 plan differs from P10 only at the selector-v2 seam."""

from __future__ import annotations

import json
from pathlib import Path

from plugins.corpus.structured.ledger import BatchPlan

HERE = Path(__file__).resolve().parent
P10_PLAN = HERE.parent / "p10-accepted-items-import-live/plan.json"


def main() -> None:
    old = BatchPlan.model_validate_json(P10_PLAN.read_text(encoding="utf-8"))
    new = BatchPlan.model_validate_json((HERE / "plan.json").read_text(encoding="utf-8"))
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

    serialized = (HERE / "plan.json").read_text(encoding="utf-8")
    raw_plan = json.loads(serialized)

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key) for key in value} | {
                nested_key for nested in value.values() for nested_key in keys(nested)
            }
        if isinstance(value, list):
            return {nested_key for nested in value for nested_key in keys(nested)}
        return set()

    if "api_key" in keys(raw_plan) or "bearer " in serialized.lower():
        raise RuntimeError("plan contains an inline credential field")
    if any(
        profile.credential_ref is None or not profile.credential_ref.startswith("env:")
        for profile in new.profiles
    ):
        raise RuntimeError("plan contains a non-reference credential binding")

    summary = {
        "schema_version": "relation-selector-v2-plan-diff-1",
        "status": "frozen_not_executed",
        "p10_batch_id": old.batch_id,
        "p12_batch_id": new.batch_id,
        "p12_plan_sha256": new.plan_sha256,
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
        "next_gate": "explicit authorization for at most four selector-v2 relation calls",
    }
    (HERE / "plan-diff-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
