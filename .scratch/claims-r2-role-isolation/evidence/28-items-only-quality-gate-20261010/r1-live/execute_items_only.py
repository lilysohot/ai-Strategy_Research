"""Execute the frozen items-only plans exactly once with no automatic rerun.

Authorized by gate revision 3 (authorized_by=xyl, 2026-10-11, model
doubao-seed-2.1-lite, 10 + 14 attempts, concurrency 1). Both batches live in
one shared store root and run sequentially. No retries: the extraction adapter
sends each request once and records the attempt. Writes live-run-summary.json
and exits non-zero on any recorded error.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FREEZE_DIR = HERE.parent / "r0-zero-call"
sys.path.insert(0, str(FREEZE_DIR))

import freeze_items_only_plan as frozen  # noqa: E402

from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import BatchPlan, execute_batch  # noqa: E402

ROOT = frozen.ROOT
STORE = HERE / "live-store"
SUMMARY = HERE / "live-run-summary.json"
ORDER = ("industrial-fulian-md", "optical-module-docx")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    if STORE.exists():
        raise RuntimeError("live store already exists; automatic rerun is forbidden")

    manifest = read_json(FREEZE_DIR / "freeze-manifest.json")
    gate = read_json(FREEZE_DIR / "preregistered-gate.json")
    auth = gate["authorization"]["items_live_extraction"]
    if auth["authorized"] is not True or auth["authorized_by"] != "xyl":
        raise RuntimeError("items live extraction is not authorized")
    if gate["countersignature"]["status"] != "signed":
        raise RuntimeError("gate is not countersigned")
    if auth["model"] != manifest["model"]:
        raise RuntimeError("authorized model does not match the frozen manifest")

    config = load_extraction_config(dotenv_path=ROOT / ".env", options=frozen.request_options())
    profile = config.require_profile()
    if (
        profile.model != "doubao-seed-2.1-lite"
        or profile.fingerprint != manifest["profile_sha256"]
        or profile.options.max_output_tokens != 262144
        or profile.options.reasoning_effort != "minimal"
    ):
        raise RuntimeError("frozen extraction profile was not restored")

    sources: dict[str, Any] = {}
    error: str | None = None
    for slug in ORDER:
        entry = next(item for item in manifest["sources"] if item["slug"] == slug)
        plan = BatchPlan.model_validate_json(
            (FREEZE_DIR / f"plan-{slug}.json").read_text(encoding="utf-8")
        )
        plan.verify_identity()
        if plan.batch_id != entry["batch_id"] or plan.plan_sha256 != entry["plan_sha256"]:
            raise RuntimeError(f"plan identity mismatch: {slug}")
        if plan.role_max_attempts["material_items"] != auth["attempts_max"][slug]:
            raise RuntimeError(f"attempt budget mismatch: {slug}")
        print(
            f"[live] executing {slug} batch={plan.batch_id} "
            f"budget={plan.role_max_attempts['material_items']}",
            flush=True,
        )
        try:
            result = execute_batch(plan, store_root=STORE, allow_model=True, config=config)
        except Exception as exc:  # record and stop; no automatic rerun
            error = f"{slug}:{type(exc).__name__}:{exc}"
            sources[slug] = {"status": "exception", "error": error}
            break
        ledger = result.ledger
        attempts = ledger.attempts
        role_by_task = {task.task_id: task.role for task in ledger.tasks}
        attempt_roles = Counter(role_by_task.get(item.task_id, "unknown") for item in attempts)
        usage = {
            key: sum((item.usage or {}).get(key) or 0 for item in attempts)
            for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
        }
        task_summary = [
            {
                "task_id": task.task_id,
                "role": task.role,
                "method": task.method,
                "execution_status": task.execution_status,
                "protocol_status": task.protocol_status,
                "quality_status": task.quality_status,
                "publication_status": task.publication_status,
                "context_status": task.context_status,
                "artifact_sha256": task.artifact_sha256,
                "error_codes": list(task.error_codes),
            }
            for task in ledger.tasks
        ]
        sources[slug] = {
            "status": "executed",
            "batch_id": ledger.batch_id,
            "plan_sha256": ledger.plan_sha256,
            "snapshot_id": ledger.snapshot_id,
            "attempts": len(attempts),
            "attempt_status": dict(Counter(item.execution_status for item in attempts)),
            "attempt_roles": dict(attempt_roles),
            "tasks": task_summary,
            "usage": usage,
            "plan_consistent": result.plan_consistent,
            "findings": list(result.findings),
            "derivations": dict(result.derivations),
            "role_budgets": {
                role: {
                    "max_attempts": budget.max_attempts,
                    "reserved_attempts": budget.reserved_attempts,
                }
                for role, budget in result.role_budgets.items()
            },
        }
        print(
            f"[live] {slug} attempts={len(attempts)} "
            f"attempt_status={sources[slug]['attempt_status']} "
            f"attempt_roles={dict(attempt_roles)}",
            flush=True,
        )
        for task in task_summary:
            print(
                f"[live] {slug} task={task['role']} "
                f"execution={task['execution_status']} protocol={task['protocol_status']} "
                f"quality={task['quality_status']} context={task['context_status']} "
                f"errors={task['error_codes']}",
                flush=True,
            )
        if set(attempt_roles) - {"material_items"}:
            error = f"{slug}:unexpected_attempt_roles:{dict(attempt_roles)}"
            break

    summary = {
        "schema_version": "items-only-live-run-summary-1",
        "executed_on": "2026-10-11",
        "model": profile.model,
        "profile_fingerprint": profile.fingerprint,
        "gate_sha256": "sha256:"
        + hashlib.sha256((FREEZE_DIR / "preregistered-gate.json").read_bytes()).hexdigest(),
        "store_root": str(STORE),
        "sources": sources,
        "error": error,
    }
    SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "written": str(SUMMARY),
                "error": error,
                "attempts_total": sum(
                    source.get("attempts", 0) for source in sources.values()
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
