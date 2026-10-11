"""Execute the re-frozen items-only plans once, paced, with no automatic rerun.

Gate revision 4 authorizes the user-directed model substitution
(deepseek-v4-flash) after the run-1 HTTP 429 burst-protection invalidation.
Pacing: a checkpoint sleeps 20 seconds after each attempt reservation and
before the request is sent (never a retry). Both batches run sequentially in
one shared store root. Writes live-run-summary.json; exits non-zero on any
recorded error.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
R0 = HERE.parent / "r0-zero-call"
R1 = HERE.parent / "r1-live"
sys.path.insert(0, str(R0))

import freeze_items_only_plan as frozen  # noqa: E402

from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import BatchPlan, execute_batch  # noqa: E402

ROOT = frozen.ROOT
STORE = HERE / "live-store"
SUMMARY = HERE / "live-run-summary.json"
PACING_SECONDS = 20.0
ORDER = ("industrial-fulian-md", "optical-module-docx")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def checkpoint(name: str) -> None:
    """Pace first attempts: wait before each send; never used for retries."""
    if name == "after_reserve":
        time.sleep(PACING_SECONDS)


def main() -> None:
    if STORE.exists():
        raise RuntimeError("live store already exists; automatic rerun is forbidden")

    replan = read_json(HERE / "replan-manifest.json")
    gate = read_json(R0 / "preregistered-gate.json")
    auth = gate["authorization"]["items_live_extraction"]
    if auth["authorized"] is not True or auth["authorized_by"] != "xyl":
        raise RuntimeError("items live extraction is not authorized")
    if gate["countersignature"]["status"] != "signed":
        raise RuntimeError("gate is not countersigned")
    if auth["model"] != replan["model"] != "deepseek-v4-flash":
        raise RuntimeError("authorized model does not match the replan manifest")
    if replan["gate_revision"] != 4:
        raise RuntimeError("replan was not bound to gate revision 4")

    config = load_extraction_config(dotenv_path=ROOT / ".env", options=frozen.request_options())
    profile = config.require_profile()
    if (
        profile.model != "deepseek-v4-flash"
        or profile.fingerprint != replan["profile_sha256"]
        or profile.options.model_dump(mode="json") != replan["request_options"]
    ):
        raise RuntimeError("re-frozen extraction profile was not restored")

    sources: dict[str, Any] = {}
    error: str | None = None
    for slug in ORDER:
        entry = next(item for item in replan["sources"] if item["slug"] == slug)
        plan = BatchPlan.model_validate_json(
            (HERE / f"plan-{slug}.json").read_text(encoding="utf-8")
        )
        plan.verify_identity()
        if plan.batch_id != entry["batch_id"] or plan.plan_sha256 != entry["plan_sha256"]:
            raise RuntimeError(f"plan identity mismatch: {slug}")
        if plan.role_max_attempts["material_items"] != auth["attempts_max"][slug]:
            raise RuntimeError(f"attempt budget mismatch: {slug}")
        print(
            f"[live-r2] executing {slug} batch={plan.batch_id} "
            f"budget={plan.role_max_attempts['material_items']} pacing={PACING_SECONDS}s",
            flush=True,
        )
        try:
            result = execute_batch(
                plan,
                store_root=STORE,
                allow_model=True,
                config=config,
                checkpoint=checkpoint,
            )
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
            f"[live-r2] {slug} attempts={len(attempts)} "
            f"attempt_status={sources[slug]['attempt_status']} "
            f"attempt_roles={dict(attempt_roles)}",
            flush=True,
        )
        for task in task_summary:
            print(
                f"[live-r2] {slug} task={task['role']} "
                f"execution={task['execution_status']} protocol={task['protocol_status']} "
                f"quality={task['quality_status']} context={task['context_status']} "
                f"errors={task['error_codes']}",
                flush=True,
            )
        if set(attempt_roles) - {"material_items"}:
            error = f"{slug}:unexpected_attempt_roles:{dict(attempt_roles)}"
            break

    summary = {
        "schema_version": "items-only-live-run-summary-r2-1",
        "executed_on": "2026-10-11",
        "gate_revision": 4,
        "model": profile.model,
        "profile_fingerprint": profile.fingerprint,
        "pacing_seconds": PACING_SECONDS,
        "gate_sha256": "sha256:"
        + hashlib.sha256((R0 / "preregistered-gate.json").read_bytes()).hexdigest(),
        "replan_manifest_sha256": "sha256:"
        + hashlib.sha256((HERE / "replan-manifest.json").read_bytes()).hexdigest(),
        "supersedes_run": {
            "run": "r1-live",
            "summary_sha256": "sha256:"
            + hashlib.sha256((R1 / "live-run-summary.json").read_bytes()).hexdigest(),
            "status": "invalidated_http_429_burst_protection",
        },
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
