"""Verify that Issue 20 changes P14 only by model and derived identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plugins.corpus.structured.ledger import BatchPlan

HERE = Path(__file__).resolve().parent
P14 = HERE.parents[1] / "18-material-extractor-replacement-20261009" / "p14-question-group-live-plan"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _without_derived_profile_identity(profile: object) -> dict[str, object]:
    value = profile.model_dump(mode="json")  # type: ignore[attr-defined]
    for key in ("model", "profile_sha256", "role_profile_sha256"):
        value.pop(key, None)
    return value


def main() -> None:
    old = BatchPlan.model_validate_json((P14 / "plan.json").read_text(encoding="utf-8"))
    new_path = HERE / "plan.json"
    new = BatchPlan.model_validate_json(new_path.read_text(encoding="utf-8"))
    old.verify_identity()
    new.verify_identity()

    frozen_fields = (
        "snapshot",
        "max_attempts",
        "role_max_attempts",
        "enabled_roles",
        "imported_material_items",
        "currency",
        "relations",
    )
    for field in frozen_fields:
        if getattr(old, field) != getattr(new, field):
            raise RuntimeError(f"frozen plan field changed: {field}")

    old_profiles = {profile.role: profile for profile in old.profiles}
    new_profiles = {profile.role: profile for profile in new.profiles}
    if old_profiles.keys() != new_profiles.keys():
        raise RuntimeError("profile roles changed")
    for role, old_profile in old_profiles.items():
        new_profile = new_profiles[role]
        if old_profile.model != "doubao-seed-2.0-mini":
            raise RuntimeError(f"unexpected P14 model: {role}")
        if new_profile.model != "glm-5.3-flash":
            raise RuntimeError(f"replacement model not frozen: {role}")
        if _without_derived_profile_identity(old_profile) != (
            _without_derived_profile_identity(new_profile)
        ):
            raise RuntimeError(f"profile changed beyond model identity: {role}")

    old_task_shape = [(task.role, task.method, task.max_attempts) for task in old.tasks]
    new_task_shape = [(task.role, task.method, task.max_attempts) for task in new.tasks]
    if old_task_shape != new_task_shape:
        raise RuntimeError("task role/method/budget shape changed")

    summary = {
        "schema_version": "relation-model-replacement-plan-diff-1",
        "status": "verified_model_only_not_executed",
        "source_batch_id": old.batch_id,
        "new_batch_id": new.batch_id,
        "new_plan_sha256": new.plan_sha256,
        "new_plan_file_sha256": _sha256(new_path),
        "final_gate_sha256": _sha256(HERE / "final-gate.json"),
        "model_requests_during_freeze": 0,
        "changed": {
            "model": {"from": "doubao-seed-2.0-mini", "to": "glm-5.3-flash"},
            "derived_identities": [
                "profile_sha256",
                "role_profile_sha256",
                "task_id",
                "routing_sha256",
                "plan_sha256",
                "batch_id",
            ],
        },
        "unchanged": {
            "snapshot_id": new.snapshot.snapshot_id,
            "imported_items": True,
            "enabled_roles": list(new.enabled_roles),
            "max_attempts": new.max_attempts,
            "role_max_attempts": new.role_max_attempts,
            "relation_candidate_rule": new.relations.rule_version,
            "items_validation_version": new.relations.items_validation_version,
            "dependency_policy": new.relations.dependency_policy,
            "protocol": new_profiles["material_relations"].protocol,
            "provider": new_profiles["material_relations"].provider,
            "base_url": new_profiles["material_relations"].base_url,
            "request_options": new_profiles["material_relations"].request_options,
            "credential_reference_only": True,
        },
        "execution_authorized": True,
        "relation_attempts_max": 4,
        "publication_authorized": False,
    }
    (HERE / "plan-diff-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
