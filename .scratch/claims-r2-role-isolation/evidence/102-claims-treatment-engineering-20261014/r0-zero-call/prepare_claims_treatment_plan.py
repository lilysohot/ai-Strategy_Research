"""Freeze the claims treatment-arm plan (95/99 号 前置缺件①): two sources, one live round, zero calls.

Reads the signed pre-registration (99 号) and the frozen snapshots of the two claims sources, re-plans
them **under the current code version** (T1–T4 landed) and writes a write-once freeze that the
executor must match byte for byte. No model call happens here, so the freeze may exist before the
budget line is filled — it records ``runnable=false`` until it is.

Fail-closed:
* the pre-registration must be signed (``frozen_before_execution``) and name exactly the four
  treatment rules this freeze implements, or the arm would not be the arm that was signed;
* every per-run attempt ceiling is read from the *signed* budget reference, never invented here.

Usage:
    python prepare_claims_treatment_plan.py [--no-write] [--force]
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

from plugins.corpus.claims_binding import CLAIMS_SLOT_PROTOCOL_VERSION  # noqa: E402
from plugins.corpus.claims_detail import (  # noqa: E402
    EXTRACTOR_VERSION_V2,
    LINT_VERSION,
    PERIOD_RULE_VERSION,
    UNIT_RULE_VERSION,
)
from plugins.corpus.evidence_pipeline import CLAIMS_ATOMIC_PROTOCOL, PIPELINE_VERSION  # noqa: E402
from plugins.corpus.structured.config import RequestOptions, load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import plan_batch  # noqa: E402
from plugins.corpus.structured.roles import ROUTING_RULE_VERSION  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

SOURCE_FREEZE = (
    ROOT / "evidence/17-structured-extraction-convergence-closure-20261009/p1r3-claims-plan-freeze"
)
SIGNED_PREREG = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
T4_LANDING = (
    ROOT
    / "evidence/100-claims-t4-labeling-landing-20261014/r0-zero-call/treatment-landing-record.json"
)
T123_LANDING = (
    ROOT
    / "evidence/101-claims-treatment-t1t2t3-landing-20261014/r0-zero-call/treatment-landing-record.json"
)
OUT = HERE / "claims-treatment-plan-freeze"
RUNS = {
    "claims-industrial-fulian": "replay-claims-industrial-fulian",
    "claims-optical-module": "replay-claims-optical-module",
}
SIGNED_TREATMENT_RULES = (
    "T1_no_opinion",
    "T2_unbound_disposition",
    "T3_dedupe_tie_break",
    "T4_missing_field_must_be_labelled",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def signed_budget() -> tuple[dict[str, object], int | None, dict[str, int]]:
    """Signed pre-registration, its global ceiling, and the per-run ceilings from its reference."""
    prereg = load(SIGNED_PREREG)
    if prereg.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to freeze: pre-registration is {prereg.get('status')!r}")
    rules = tuple(
        rule["id"]
        for rule in prereg["pre_registered_treatment_rules"]["rules"]  # type: ignore[index]
    )
    if sorted(rules) != sorted(SIGNED_TREATMENT_RULES):
        raise SystemExit(f"refusing to freeze: signed treatment rules are {rules!r}")
    budget = prereg["budget_request"]["stage_1_live_run"]  # type: ignore[index]
    ceiling = budget.get("requested_ceiling")
    if ceiling is not None and not isinstance(ceiling, int):
        raise SystemExit(f"refusing to freeze: ceiling {ceiling!r} is not an integer")
    reference = budget["historical_reference"]
    per_run = {
        str(item["name"]): int(item["attempt_ceiling"]) for item in reference["per_execution"]
    }
    missing = [name for name in RUNS if name not in per_run]
    if missing:
        raise SystemExit(f"refusing to freeze: signed reference lacks ceilings for {missing}")
    return prereg, ceiling, per_run


def build() -> tuple[dict[str, object], dict[str, bytes]]:
    _prereg, ceiling, per_run = signed_budget()
    config = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env", options=RequestOptions(max_output_tokens=16_384)
    )
    profile = config.require_profile()
    entries: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    for name, source_dir in RUNS.items():
        source = SOURCE_FREEZE / source_dir
        snapshot = EvidenceSnapshot.model_validate_json(
            (source / "snapshot.json").read_text(encoding="utf-8")
        )
        snapshot.verify_identity()
        attempt_ceiling = per_run[name]
        # The whole point: re-plan under the *current* code version (T1–T4 landed), not the old one.
        plan = plan_batch(
            snapshot,
            config=config,
            max_attempts=attempt_ceiling,
            role_max_attempts={
                "claims": attempt_ceiling,
                "material_items": 0,
                "material_relations": 0,
            },
            relations_enabled=False,
            max_relation_tasks=0,
            max_relation_attempts=0,
            enabled_roles=("claims",),
        )
        plan.verify_identity()
        claims_task = next(task for task in plan.tasks if task.role == "claims")
        snapshot_bytes = (
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        plan_bytes = (
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        payloads[f"{name}/snapshot.json"] = snapshot_bytes
        payloads[f"{name}/plan.json"] = plan_bytes
        entries.append(
            {
                "name": name,
                "mode": "live_model",
                "source_snapshot": str((source / "snapshot.json").relative_to(ROOT)),
                "source_snapshot_sha256": sha256(source / "snapshot.json"),
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "attempt_ceiling": attempt_ceiling,
                "scoped_units": len(claims_task.scoped_unit_ids),
                "protocol": claims_task.protocol,
                "snapshot_file_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                "plan_file_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            }
        )
    total_ceiling = sum(int(entry["attempt_ceiling"]) for entry in entries)
    manifest: dict[str, object] = {
        "schema_version": "claims-treatment-plan-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-14",
        "purpose": (
            "冻结治疗臂（T1–T4 落地后的当前代码版本）两源一次全量抽取的计划；"
            "execute_claims_treatment.py 是唯一执行入口，未授权预算时拒绝执行。"
        ),
        "prereg": {
            "path": str(SIGNED_PREREG.relative_to(ROOT)),
            "sha256": sha256(SIGNED_PREREG),
            "treatment_rules": list(SIGNED_TREATMENT_RULES),
        },
        "treatment_landing": {
            "t4": {"path": str(T4_LANDING.relative_to(ROOT)), "sha256": sha256(T4_LANDING)},
            "t1_t2_t3": {
                "path": str(T123_LANDING.relative_to(ROOT)),
                "sha256": sha256(T123_LANDING),
            },
        },
        "budget": {
            "requested_ceiling": ceiling,
            "per_run_ceilings": per_run,
            "total_attempt_ceiling": total_ceiling,
            "authorised": ceiling is not None,
            "note": "ceiling 由 U 填在已签预注册件里；未填时本冻结件合法存在但不可执行",
        },
        "runnable": False,
        "runnable_note": (
            "缺一不可：①簽认件 ceiling 非空 ②执行者显式 --allow-model ③profile 指纹与冻结计划一致"
        ),
        "versions": {
            "claims_protocol": CLAIMS_ATOMIC_PROTOCOL,
            "slot_protocol": CLAIMS_SLOT_PROTOCOL_VERSION,
            "routing": ROUTING_RULE_VERSION,
            "extractor": EXTRACTOR_VERSION_V2,
            "pipeline": PIPELINE_VERSION,
            "lint": LINT_VERSION,
            "period_rules": PERIOD_RULE_VERSION,
            "unit_rules": UNIT_RULE_VERSION,
        },
        "profile": {
            "model": profile.model,
            "adapter_version": profile.adapter_version,
            "profile_sha256": profile.fingerprint,
            "request_options": profile.options.model_dump(mode="json"),
        },
        "entries": entries,
        "maximum_new_model_calls": total_ceiling,
        "automatic_retries": 0,
        "gold_not_exposed_to_model": True,
        "production_database_access": 0,
        "publication_writes": 0,
        "prepare_script_sha256": sha256(Path(__file__)),
    }
    return manifest, payloads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest, payloads = build()
    outputs: dict[str, bytes] = dict(payloads)
    outputs["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    if args.no_write:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("[no-write] freeze computed; nothing written.")
        return 0

    targets = {name: OUT / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="102 号治疗计划冻结件")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)
    print(f"wrote {len(outputs)} files to {OUT}")
    print(json.dumps(manifest["budget"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
