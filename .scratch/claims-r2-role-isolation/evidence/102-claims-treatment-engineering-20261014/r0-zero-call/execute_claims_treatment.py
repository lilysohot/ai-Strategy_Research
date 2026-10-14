"""The only live entry of the claims treatment arm (95/99 号 前置缺件①): refuse unless authorised.

Gates, all fail-closed, checked *before* any model call:

1. the pre-registration is signed and still names the four treatment rules (T1–T4);
2. its ``budget_request.stage_1_live_run.requested_ceiling`` is filled — "未填预算不得起跑";
3. the freeze manifest exists and every plan file hash matches it (drift blocks the run);
4. the configured extraction profile fingerprint equals the frozen one (endpoint/model swap mid-flight
   is the failure mode that invalidated a previous arm);
5. ``--allow-model`` is passed explicitly;
6. the authorised ceiling covers the frozen per-run ceilings.

``--dry-run`` performs all six gates and prints what *would* run, without a single call — that is how
this entry is exercised while the budget line is empty.

Usage:
    python execute_claims_treatment.py --dry-run
    python execute_claims_treatment.py --allow-model        # only after the ceiling is filled
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured.config import (  # noqa: E402
    RequestOptions,
    load_extraction_config,
)
from plugins.corpus.structured.ledger import BatchCheck, BatchPlan, execute_batch  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

FREEZE = HERE / "claims-treatment-plan-freeze"
SIGNED_PREREG = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
BUDGET_AUTHORISATION = (
    ROOT
    / "evidence/103-claims-budget-authorisation-20261014/r0-zero-call/budget-authorisation.json"
)
SIGNED_TREATMENT_RULES = (
    "T1_no_opinion",
    "T2_unbound_disposition",
    "T3_dedupe_tie_break",
    "T4_missing_field_must_be_labelled",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def authorised_budget() -> dict[str, Any]:
    """The authorised ceiling for the round, refusing anything but a filled, positive integer.

    The signed pre-registration leaves that leaf blank (``filled_by: U``); the number lives in the
    103-号 authorisation record, which must name the *same* pre-registration by hash. Without that
    record the signed leaf is the fallback — and it is ``null``, so the run is refused.
    """
    prereg = load(SIGNED_PREREG)
    if prereg.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to run: pre-registration is {prereg.get('status')!r}")
    rules = tuple(rule["id"] for rule in prereg["pre_registered_treatment_rules"]["rules"])
    if sorted(rules) != sorted(SIGNED_TREATMENT_RULES):
        raise SystemExit(f"refusing to run: signed treatment rules are {rules!r}")
    if BUDGET_AUTHORISATION.exists():
        authorisation = load(BUDGET_AUTHORISATION)
        if authorisation["signed_prereg"]["sha256"] != sha256(SIGNED_PREREG):
            raise SystemExit(
                "refusing to run: budget authorisation names a different pre-registration"
            )
        value = authorisation["budget"].get("ceiling_value")
        unit = authorisation["budget"].get("ceiling_unit")
        if not isinstance(value, int) or value <= 0 or not unit:
            raise SystemExit(f"refusing to run: 授权件里的 ceiling 无效（{value!r} {unit!r}）")
        return {
            "value": value,
            "unit": unit,
            "source": str(BUDGET_AUTHORISATION.relative_to(ROOT)),
            "per_run": authorisation.get("per_run_attempt_ceilings") or {},
            "stated_by": authorisation["budget"].get("stated_by"),
            "stated_how": authorisation["budget"].get("stated_how"),
        }
    ceiling = prereg["budget_request"]["stage_1_live_run"].get("requested_ceiling")
    if not isinstance(ceiling, int) or ceiling <= 0:
        raise SystemExit(
            "refusing to run: budget_request.stage_1_live_run.requested_ceiling 未填（由 U 填）"
            " 且无预算授权件 ⇒ 按 99 号『未填预算不得起跑』拒绝执行"
        )
    return {"value": ceiling, "unit": "tokens", "source": "signed prereg leaf", "per_run": {}}


def tokens_used(freeze: Path, names: list[str]) -> dict[str, Any]:
    """Sum ``total_tokens`` from the ledger's own ``attempts.usage`` — the source the ceiling names."""
    per_run: dict[str, int] = {}
    for name in names:
        index = freeze / name / "live-store/index/structured.sqlite3"
        if not index.exists():
            continue
        connection = sqlite3.connect(index)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT usage FROM attempts").fetchall()
        finally:
            connection.close()
        total = 0
        for row in rows:
            usage = row["usage"]
            if usage:
                total += int(json.loads(usage).get("total_tokens") or 0)
        per_run[name] = total
    return {"per_run": per_run, "total_tokens": sum(per_run.values())}


def frozen_plans() -> tuple[dict[str, Any], list[tuple[str, BatchPlan]]]:
    if not (FREEZE / "manifest.json").exists():
        raise SystemExit(f"refusing to run: no plan freeze at {FREEZE}（先跑 prepare）")
    manifest = load(FREEZE / "manifest.json")
    if manifest.get("status") != "frozen_not_executed":
        raise SystemExit(f"refusing to run: freeze status is {manifest.get('status')!r}")
    plans: list[tuple[str, BatchPlan]] = []
    for entry in manifest["entries"]:
        name = str(entry["name"])
        path = FREEZE / name / "plan.json"
        if not path.exists() or sha256(path) != entry["plan_file_sha256"]:
            raise SystemExit(f"refusing to run: plan file drifted for {name}")
        if sha256(FREEZE / name / "snapshot.json") != entry["snapshot_file_sha256"]:
            raise SystemExit(f"refusing to run: snapshot file drifted for {name}")
        plan = BatchPlan.model_validate_json(path.read_text(encoding="utf-8"))
        plan.verify_identity()
        if plan.plan_sha256 != entry["plan_sha256"]:
            raise SystemExit(f"refusing to run: plan identity drifted for {name}")
        plans.append((name, plan))
    return manifest, plans


def summarize(name: str, checked: BatchCheck) -> dict[str, Any]:
    tasks = [task for task in checked.ledger.tasks if task.role == "claims"]
    task_ids = {task.task_id for task in tasks}
    attempts = [attempt for attempt in checked.ledger.attempts if attempt.task_id in task_ids]
    return {
        "name": name,
        "execution_mode": "live_model",
        "ledger_attempts": len(attempts),
        "new_model_calls": sum(attempt.provider != "replay" for attempt in attempts),
        "attempt_status": dict(Counter(attempt.execution_status for attempt in attempts)),
        "task_status": dict(Counter(task.execution_status for task in tasks)),
        "protocol_status": dict(Counter(task.protocol_status for task in tasks)),
        "quality_status": dict(Counter(task.quality_status for task in tasks)),
        "publication_status": dict(Counter(task.publication_status for task in tasks)),
        "findings": list(checked.findings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    budget = authorised_budget()
    ceiling = int(budget["value"])
    manifest, plans = frozen_plans()
    if sum(int(entry["attempt_ceiling"]) for entry in manifest["entries"]) > ceiling:
        raise SystemExit(
            f"refusing to run: frozen ceilings {manifest['maximum_new_model_calls']} > 授权 ceiling {ceiling}"
        )
    for entry in manifest["entries"]:
        authorised = budget["per_run"].get(str(entry["name"]))
        if authorised is not None and int(entry["attempt_ceiling"]) > int(authorised):
            raise SystemExit(
                f"refusing to run: {entry['name']} 计划上限 {entry['attempt_ceiling']} > 授权 {authorised}"
            )
    config = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env", options=RequestOptions(max_output_tokens=16_384)
    )
    profile = config.require_profile()
    if profile.fingerprint != manifest["profile"]["profile_sha256"]:
        raise SystemExit("refusing to run: configured profile does not match the frozen plan")

    plan_summary = [
        {
            "name": name,
            "batch_id": plan.batch_id,
            "attempt_ceiling": next(
                entry["attempt_ceiling"] for entry in manifest["entries"] if entry["name"] == name
            ),
        }
        for name, plan in plans
    ]
    if args.dry_run or not args.allow_model:
        print(
            json.dumps(
                {
                    "gates": {
                        "prereg_signed": True,
                        "budget_ceiling": ceiling,
                        "budget_unit": budget["unit"],
                        "budget_source": budget["source"],
                        "budget_stated_by": budget.get("stated_by"),
                        "freeze_manifest_sha256": sha256(FREEZE / "manifest.json"),
                        "profile_matches": True,
                        "allow_model": args.allow_model,
                    },
                    "would_run": plan_summary,
                    "note": "零调用；未传 --allow-model 时本入口只做闸门检查",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if args.dry_run else 1

    output = FREEZE / "execution-summary.json"
    assert_writable(output, reason="102 号治疗臂实跑记录")
    if output.exists():
        raise SystemExit("refusing to overwrite the treatment execution summary")
    results: list[dict[str, Any]] = []
    for name, plan in plans:
        checked = execute_batch(
            plan,
            store_root=FREEZE / name / "live-store",
            allow_model=True,
            config=config,
        )
        result = summarize(name, checked)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    usage = tokens_used(FREEZE, [name for name, _plan in plans])
    exceeded = usage["total_tokens"] > ceiling
    summary = {
        "schema_version": "claims-treatment-execution-1",
        "executed_on": "2026-10-14",
        "freeze_manifest_sha256": sha256(FREEZE / "manifest.json"),
        "prereg_sha256": sha256(SIGNED_PREREG),
        "authorised_ceiling": ceiling,
        "authorised_unit": budget["unit"],
        "budget_source": budget["source"],
        "new_model_calls": sum(cast(int, item["new_model_calls"]) for item in results),
        "tokens_used": usage,
        "budget_exceeded": exceeded,
        "budget_verdict": ("超限：按 103 号授权判该轮无效并登记" if exceeded else "在授权额度内"),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "results": results,
        "next_action": "阶段 2 零调用止损（按已签判据）→ 新池裁定工作表（阶段 3）",
    }
    write_once(output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if exceeded else 0


if __name__ == "__main__":
    raise SystemExit(main())
