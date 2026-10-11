"""Execute one frozen arm of the issue-32 gate, one source per invocation.

Fails closed on any authorization, profile, plan or budget drift. Pacing is a 20-second
sleep before each request is sent (never a retry). Each arm/source pair owns its own store
root. If a store already holds a finished ledger for the plan, the summary is rebuilt from
that ledger with zero model calls instead of re-running anything.

Usage:
    uv run python .../live/execute_arm.py --arm control --source md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E32 = HERE.parent
CLAIMS = E32.parent.parent
R0 = E32 / "r0-zero-call"
ROOT = Path(__file__).resolve().parents[5]
PACING_SECONDS = 20.0
SLUGS = {"md": "industrial-fulian-md", "docx": "optical-module-docx"}

from plugins.corpus.structured.config import RequestOptions, load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import (  # noqa: E402
    BatchCheck,
    BatchPlan,
    check_batch,
    execute_batch,
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def checkpoint(name: str) -> None:
    if name == "after_reserve":
        time.sleep(PACING_SECONDS)


def summarize(
    result: BatchCheck,
    *,
    store: Path,
    expected: int,
    provenance: str,
    duration_seconds: float | None,
) -> dict[str, Any]:
    ledger = result.ledger
    attempts = ledger.attempts
    role_by_task = {task.task_id: task.role for task in ledger.tasks}
    attempt_roles = Counter(role_by_task.get(item.task_id, "unknown") for item in attempts)
    usage: dict[str, int] = {
        key: sum((item.usage or {}).get(key) or 0 for item in attempts)
        for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
    }
    return {
        "status": "executed",
        "provenance": provenance,
        "batch_id": ledger.batch_id,
        "plan_sha256": ledger.plan_sha256,
        "snapshot_id": ledger.snapshot_id,
        "store_root": str(store),
        "duration_seconds": duration_seconds,
        "attempts": len(attempts),
        "expected_attempts": expected,
        "attempt_status": dict(Counter(item.execution_status for item in attempts)),
        "attempt_roles": dict(attempt_roles),
        "attempt_usage": [
            {
                "attempt_number": item.attempt_number,
                "execution_status": item.execution_status,
                "usage": item.usage,
                "response_model": item.response_model,
            }
            for item in attempts
        ],
        "usage": usage,
        "reasoning_tokens_field_present": any(
            item.usage is not None and "reasoning_tokens" in item.usage for item in attempts
        ),
        "plan_consistent": result.plan_consistent,
        "findings": list(result.findings),
        "tasks": [
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
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="execute_arm")
    parser.add_argument("--arm", choices=("control", "treatment"), required=True)
    parser.add_argument("--source", choices=("md", "docx"), required=True)
    args = parser.parse_args()

    gate = read_json(R0 / "preregistered-gate.json")
    manifest = read_json(R0 / "freeze-manifest.json")
    if gate["countersignature"]["status"] != "signed":
        raise RuntimeError("gate is not countersigned")
    auth = gate["authorization"]["items_live_extraction"]
    if auth["authorized"] is not True or auth["authorized_by"] != "xyl":
        raise RuntimeError("items live extraction is not authorized")
    if auth["pacing_seconds"] != PACING_SECONDS:
        raise RuntimeError("pacing drifted from the frozen gate")

    arm = manifest["arms"][args.arm]
    slug = SLUGS[args.source]
    entry = next(item for item in arm["sources"] if item["slug"] == slug)
    expected = auth["attempts_max"][slug]
    if entry["expected_attempts"] != expected:
        raise RuntimeError("authorized attempts do not match the frozen plan")

    options = RequestOptions.model_validate(arm["request_options"])
    config = load_extraction_config(dotenv_path=ROOT / ".env", options=options)
    profile = config.require_profile()
    if profile.model != auth["model"] or profile.model != arm["model"]:
        raise RuntimeError("authorized model does not match the frozen arm")
    if profile.fingerprint != arm["profile_sha256"]:
        raise RuntimeError("frozen arm profile was not restored")
    if profile.options.model_dump(mode="json") != arm["request_options"]:
        raise RuntimeError("frozen arm request options were not restored")

    plan = BatchPlan.model_validate_json(
        (R0 / f"plan-{args.arm}-{slug}.json").read_text(encoding="utf-8")
    )
    plan.verify_identity()
    if plan.batch_id != entry["batch_id"] or plan.plan_sha256 != entry["plan_sha256"]:
        raise RuntimeError("plan identity mismatch")
    if plan.role_max_attempts["material_items"] != expected:
        raise RuntimeError("plan attempt budget mismatch")

    store = HERE / f"{args.arm}-store" / slug
    summary_path = HERE / f"{args.arm}-run-summary.json"
    if summary_path.exists():
        summary = read_json(summary_path)
        if slug in summary["sources"]:
            raise RuntimeError(f"{args.arm}/{slug} already summarised; reruns are forbidden")
    else:
        summary = {
            "schema_version": "items-v6-reasoning-live-summary-1",
            "arm": args.arm,
            "protocol": arm["protocol"],
            "model": profile.model,
            "profile_sha256": profile.fingerprint,
            "request_options": arm["request_options"],
            "pacing_seconds": PACING_SECONDS,
            "gate_sha256": digest(R0 / "preregistered-gate.json"),
            "freeze_manifest_sha256": digest(R0 / "freeze-manifest.json"),
            "executed_on": "2026-10-11",
            "sources": {},
            "errors": [],
        }

    if store.exists():
        existing = check_batch(plan.batch_id, store_root=str(store))
        if existing.ledger.attempts:
            summary["sources"][slug] = summarize(
                existing,
                store=store,
                expected=expected,
                provenance="recovered_from_store_zero_call",
                duration_seconds=None,
            )
            summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "arm": args.arm,
                        "slug": slug,
                        "provenance": "recovered_from_store_zero_call",
                        "attempts": len(existing.ledger.attempts),
                        "usage": summary["sources"][slug]["usage"],
                        "tasks": summary["sources"][slug]["tasks"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )
            return

    print(
        f"[arm={args.arm}] executing {slug} batch={plan.batch_id} "
        f"budget={expected} pacing={PACING_SECONDS}s model={profile.model}",
        flush=True,
    )
    started = time.monotonic()
    try:
        result = execute_batch(
            plan,
            store_root=store,
            allow_model=True,
            config=config,
            checkpoint=checkpoint,
        )
    except Exception as exc:  # record and stop; no automatic rerun
        summary["errors"].append(f"{slug}:{type(exc).__name__}:{exc}")
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise

    summary["sources"][slug] = summarize(
        result,
        store=store,
        expected=expected,
        provenance="executed_live",
        duration_seconds=round(time.monotonic() - started, 1),
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "arm": args.arm,
                "slug": slug,
                "provenance": "executed_live",
                "attempts": summary["sources"][slug]["attempts"],
                "attempt_status": summary["sources"][slug]["attempt_status"],
                "usage": summary["sources"][slug]["usage"],
                "tasks": summary["sources"][slug]["tasks"],
                "duration_seconds": summary["sources"][slug]["duration_seconds"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
