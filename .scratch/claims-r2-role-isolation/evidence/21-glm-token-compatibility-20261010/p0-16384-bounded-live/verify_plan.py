"""Verify that Issue 21 changes Issue 20 only by the output-token option."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from plugins.corpus.structured.ledger import BatchPlan

HERE = Path(__file__).resolve().parent
ISSUE20 = (
    HERE.parents[1]
    / "20-relation-model-replacement-20261010"
    / "p0-glm-5-3-flash-bounded-live"
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_profile(profile: object) -> dict[str, object]:
    value = profile.model_dump(mode="json")  # type: ignore[attr-defined]
    value.pop("profile_sha256", None)
    value.pop("role_profile_sha256", None)
    options = dict(value["request_options"])  # type: ignore[arg-type]
    options.pop("max_output_tokens", None)
    value["request_options"] = options
    return value


def _request_options(profile: object) -> dict[str, Any]:
    value = getattr(profile, "request_options", None)
    if not isinstance(value, dict):
        raise RuntimeError("profile request options are missing")
    return cast(dict[str, Any], value)


def main() -> None:
    old = BatchPlan.model_validate_json(
        (ISSUE20 / "plan.json").read_text(encoding="utf-8")
    )
    new_path = HERE / "plan.json"
    new = BatchPlan.model_validate_json(new_path.read_text(encoding="utf-8"))
    old.verify_identity()
    new.verify_identity()

    for field in (
        "snapshot",
        "max_attempts",
        "role_max_attempts",
        "enabled_roles",
        "imported_material_items",
        "currency",
        "relations",
    ):
        if getattr(old, field) != getattr(new, field):
            raise RuntimeError(f"frozen plan field changed: {field}")

    old_profiles = {profile.role: profile for profile in old.profiles}
    new_profiles = {profile.role: profile for profile in new.profiles}
    if old_profiles.keys() != new_profiles.keys():
        raise RuntimeError("profile roles changed")
    for role, old_profile in old_profiles.items():
        new_profile = new_profiles[role]
        if old_profile.model != "glm-5.3-flash" or new_profile.model != "glm-5.3-flash":
            raise RuntimeError(f"model changed: {role}")
        if _request_options(old_profile)["max_output_tokens"] != 4096:
            raise RuntimeError(f"unexpected Issue 20 output limit: {role}")
        if _request_options(new_profile)["max_output_tokens"] != 16384:
            raise RuntimeError(f"16K output limit not frozen: {role}")
        if _normalize_profile(old_profile) != _normalize_profile(new_profile):
            raise RuntimeError(f"profile changed beyond output limit: {role}")

    old_task_shape = [(task.role, task.method, task.max_attempts) for task in old.tasks]
    new_task_shape = [(task.role, task.method, task.max_attempts) for task in new.tasks]
    if old_task_shape != new_task_shape:
        raise RuntimeError("task role/method/budget shape changed")

    relation = new_profiles["material_relations"]
    summary = {
        "schema_version": "glm-token-compatibility-plan-diff-1",
        "status": "verified_output_limit_only_not_executed",
        "source_batch_id": old.batch_id,
        "new_batch_id": new.batch_id,
        "new_plan_sha256": new.plan_sha256,
        "new_plan_file_sha256": _sha256(new_path),
        "final_gate_sha256": _sha256(HERE / "final-gate.json"),
        "model_requests_during_freeze": 0,
        "changed": {
            "max_output_tokens": {"from": 4096, "to": 16384},
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
            "model": relation.model,
            "provider": relation.provider,
            "base_url": relation.base_url,
            "timeout_seconds": _request_options(relation)["timeout_seconds"],
            "token_parameter": _request_options(relation)["token_parameter"],
            "snapshot_id": new.snapshot.snapshot_id,
            "imported_items": True,
            "candidate_rule": new.relations.rule_version,
            "items_validation": new.relations.items_validation_version,
            "dependency_policy": new.relations.dependency_policy,
            "protocol": relation.protocol,
            "role_max_attempts": new.role_max_attempts,
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
