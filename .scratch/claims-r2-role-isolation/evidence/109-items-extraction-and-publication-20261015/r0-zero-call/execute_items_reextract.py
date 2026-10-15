"""The only live entry of the 109-号 items re-extraction: refuse unless authorised.

Gates, all fail-closed, checked *before* any model call:

1. the pre-registration is signed (``frozen_before_execution``) and scoped to material_items only;
2. the budget authorisation exists, is positive, and the pre-registration binds it by sha256
   — "预算未授权不得起跑";
3. the freeze manifest exists and every snapshot/plan file hash matches it (drift blocks the run);
4. the configured extraction profile fingerprint equals the frozen one (endpoint/model swap
   mid-flight invalidated a previous arm);
5. ``--allow-model`` is passed explicitly;
6. the frozen attempt ceilings do not exceed the authorisation.

``--dry-run`` performs all six gates and prints what *would* run, without a single call. After the
run, ``total_tokens`` is reconciled from the ledger's own ``attempts.usage``; exceeding the ceiling
marks the round invalid (exit 1), 同 103 号语义.

Usage:
    python execute_items_reextract.py --dry-run
    python execute_items_reextract.py --allow-model        # only after P1 签认 + 预算
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

from plugins.corpus.structured.ledger import BatchCheck, BatchPlan, execute_batch  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

PREREG = HERE / "items-reextraction-preregistration-v2.json"
AUTHORISATION = HERE / "budget-authorisation-r2.json"
FREEZE = HERE / "items-reextract-plan-freeze"
FREEZE_RESOLVED = FREEZE
FREEZE_28 = ROOT / "evidence/28-items-only-quality-gate-20261010/r0-zero-call"


def extraction_config() -> Any:
    """The exact config construction prepare froze (28-号 calibrated options) — profile parity."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "freeze_items_only_plan_28", FREEZE_28 / "freeze_items_only_plan.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.config()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def authorised_budget() -> dict[str, Any]:
    """The authorised token ceiling, refusing anything but a filled, hash-bound authorisation."""
    prereg = load(PREREG)
    if prereg.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to run: pre-registration is {prereg.get('status')!r}")
    if prereg.get("role_scope") != ["material_items"]:
        raise SystemExit(f"refusing to run: unexpected role_scope {prereg.get('role_scope')!r}")
    binding = prereg["budget_request"]["stage_1_live_run"]["authorisation_record"]
    if not AUTHORISATION.exists():
        raise SystemExit("refusing to run: 109 号预算授权件不存在（未授权不得起跑）")
    if binding["sha256"] != sha256(AUTHORISATION):
        raise SystemExit("refusing to run: 预注册件绑定的授权件哈希与磁盘不一致")
    authorisation = load(AUTHORISATION)
    if authorisation["status"] not in (
        "stated_effective_pending_countersignature",
        "countersigned_effective",
    ):
        raise SystemExit(f"refusing to run: 授权件状态 {authorisation['status']!r} 不生效")
    value = authorisation["budget"].get("ceiling_total_tokens")
    if not isinstance(value, int) or value <= 0:
        raise SystemExit(f"refusing to run: 授权 ceiling 无效（{value!r}）")
    return {
        "value": value,
        "unit": "total_tokens",
        "attempts_ceiling": authorisation["budget"].get("attempts_ceiling"),
        "source": (
            str(AUTHORISATION.relative_to(ROOT))
            if AUTHORISATION.is_relative_to(ROOT)
            else str(AUTHORISATION)
        ),
        "authorisation_status": authorisation["status"],
    }


def tokens_used(names: list[str]) -> dict[str, Any]:
    """Sum ``total_tokens`` from the ledger's own ``attempts.usage`` — the source the ceiling names."""
    per_run: dict[str, int] = {}
    for slug in names:
        index = FREEZE_RESOLVED / slug / "live-store/index/structured.sqlite3"
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
        per_run[slug] = total
    return {"per_run": per_run, "total_tokens": sum(per_run.values())}


def frozen_plans() -> tuple[dict[str, Any], list[tuple[str, BatchPlan]]]:
    if not (FREEZE_RESOLVED / "manifest.json").exists():
        raise SystemExit(f"refusing to run: no plan freeze at {FREEZE_RESOLVED}（先跑 prepare）")
    manifest = load(FREEZE_RESOLVED / "manifest.json")
    if manifest.get("status") != "frozen_not_executed":
        raise SystemExit(f"refusing to run: freeze status is {manifest.get('status')!r}")
    plans: list[tuple[str, BatchPlan]] = []
    for entry in manifest["entries"]:
        slug = str(entry["slug"])
        path = FREEZE_RESOLVED / slug / "plan.json"
        if not path.exists() or sha256(path) != entry["plan_file_sha256"]:
            raise SystemExit(f"refusing to run: plan file drifted for {slug}")
        if sha256(FREEZE_RESOLVED / slug / "snapshot.json") != entry["snapshot_file_sha256"]:
            raise SystemExit(f"refusing to run: snapshot file drifted for {slug}")
        plan = BatchPlan.model_validate_json(path.read_text(encoding="utf-8"))
        plan.verify_identity()
        if plan.plan_sha256 != entry["plan_sha256"]:
            raise SystemExit(f"refusing to run: plan identity drifted for {slug}")
        plans.append((slug, plan))
    return manifest, plans


def summarize(slug: str, checked: BatchCheck) -> dict[str, Any]:
    tasks = [task for task in checked.ledger.tasks if task.role == "material_items"]
    task_ids = {task.task_id for task in tasks}
    attempts = [attempt for attempt in checked.ledger.attempts if attempt.task_id in task_ids]
    return {
        "slug": slug,
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
    parser.add_argument(
        "--freeze-dir",
        type=Path,
        default=FREEZE,
        help="round-1 evidence stays at the default; a restarted round points at its own freeze",
    )
    args = parser.parse_args()
    freeze_dir = args.freeze_dir if args.freeze_dir.is_absolute() else HERE / args.freeze_dir
    global FREEZE_RESOLVED
    FREEZE_RESOLVED = freeze_dir

    budget = authorised_budget()
    ceiling = int(budget["value"])
    manifest, plans = frozen_plans()
    frozen_attempts = sum(int(entry["attempt_ceiling"]) for entry in manifest["entries"])
    if frozen_attempts > ceiling:
        raise SystemExit(
            f"refusing to run: frozen attempts {manifest['maximum_new_model_calls']} > "
            f"授权 ceiling {ceiling}"
        )
    attempts_ceiling = budget.get("attempts_ceiling")
    if attempts_ceiling is not None and frozen_attempts > int(attempts_ceiling):
        raise SystemExit(
            f"refusing to run: frozen attempts {frozen_attempts} > U 给定 attempts 上限 {attempts_ceiling}"
        )
    config = extraction_config()
    profile = config.require_profile()
    if profile.fingerprint != manifest["profile"]["profile_sha256"]:
        raise SystemExit("refusing to run: configured profile does not match the frozen plan")

    plan_summary = [
        {
            "slug": slug,
            "batch_id": plan.batch_id,
            "attempt_ceiling": next(
                entry["attempt_ceiling"] for entry in manifest["entries"] if entry["slug"] == slug
            ),
        }
        for slug, plan in plans
    ]
    if args.dry_run or not args.allow_model:
        print(
            json.dumps(
                {
                    "gates": {
                        "prereg_signed": True,
                        "authorisation_bound": True,
                        "authorisation_status": budget["authorisation_status"],
                        "ceiling_total_tokens": ceiling,
                        "budget_source": budget["source"],
                        "freeze_manifest_sha256": sha256(FREEZE_RESOLVED / "manifest.json"),
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

    output = FREEZE_RESOLVED / "execution-summary.json"
    assert_writable(output, reason="109 号 items 重写实跑记录")
    if output.exists():
        raise SystemExit("refusing to overwrite the execution summary")
    results: list[dict[str, Any]] = []
    for slug, plan in plans:
        checked = execute_batch(
            plan,
            store_root=FREEZE_RESOLVED / slug / "live-store",
            allow_model=True,
            config=config,
        )
        result = summarize(slug, checked)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    usage = tokens_used([slug for slug, _plan in plans])
    exceeded = usage["total_tokens"] > ceiling
    summary = {
        "schema_version": "items-reextract-execution-1",
        "executed_on": "2026-10-15",
        "freeze_manifest_sha256": sha256(FREEZE_RESOLVED / "manifest.json"),
        "prereg_sha256": sha256(PREREG),
        "authorisation_sha256": sha256(AUTHORISATION),
        "authorised_ceiling_total_tokens": ceiling,
        "budget_source": budget["source"],
        "new_model_calls": sum(cast(int, item["new_model_calls"]) for item in results),
        "tokens_used": usage,
        "budget_exceeded": exceeded,
        "budget_verdict": ("超限：按 109 号授权判该轮无效并登记" if exceeded else "在授权额度内"),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "results": results,
        "next_action": "阶段 2 零调用止损（按已签 stage2_gates）→ items 裁定工作表（含 92 号 29 条 checklist）",
    }
    write_once(output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if exceeded else 0


if __name__ == "__main__":
    raise SystemExit(main())
