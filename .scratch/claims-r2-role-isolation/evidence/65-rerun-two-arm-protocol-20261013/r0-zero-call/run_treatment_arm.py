#!/usr/bin/env python3
"""Treatment-arm execution of the three preregistered packets (65 protocol).

Plan lineage: the parent snapshot comes from the frozen replay plan
``16-r5-zero-model-replay-20261008-r3/industrial-fulian-md/plan.json`` (run-1's own
batch shape: relations disabled, one items task per packet). Model is the ONLY variable
vs run-1 — prompt, protocol, code path and packets are identical.

Default mode is zero-call packet prep (snapshot subset + plan freeze + request list).
``--live`` executes: one items task per packet, up to 2 attempts (1 + 1 automatic
retry — run-1's loss cause was automatic_retries=0), 20 s throttle between packets,
hard budget guard of 9 calls. Treatment output is recorded as **never entering scoring**.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.config import (  # noqa: E402
    ExtractionConfig,
    RequestOptions,
    load_extraction_config,
)
from plugins.corpus.structured.ledger import BatchPlan, execute_batch, plan_batch  # noqa: E402
from plugins.corpus.structured.snapshot import (  # noqa: E402
    EvidenceSnapshot,
    SnapshotIdentityInput,
    _canonical_hash,
    _identity_of,
)

PARENT_PLAN = (
    REPO_ROOT
    / ".scratch/claims-r2-role-isolation/evidence/16-r5-zero-model-replay-20261008-r3"
    / "industrial-fulian-md/plan.json"
)
PROTOCOL_DIR = (
    REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence/65-rerun-two-arm-protocol-20261013"
)
ARM_OUTPUT = {
    "treatment": PROTOCOL_DIR / "r2-treatment-adjusted",
    "control": PROTOCOL_DIR / "r3-control-live",
    "control-official": PROTOCOL_DIR / "r4-control-official",
}
# Control arm: gate-28 FROZEN request_options, verbatim (timeout 300 / max_output_tokens
# 262144 / token_parameter max_tokens / reasoning_effort minimal — DeepSeek documents
# "minimal" and maps it to low). Treatment arm: user-authorized adjustment 2026-10-13 —
# the same 262144 output budget plus the Ark-native thinking switch, because doubao burned
# 12k+ reasoning tokens and starved the JSONL body at the default cap. This is a DECLARED
# second variable on the treatment arm (recorded in every manifest).
ARM_OPTIONS: dict[str, Callable[[], RequestOptions]] = {
    "control": lambda: RequestOptions(
        timeout_seconds=300.0,
        max_output_tokens=262144,
        token_parameter="max_tokens",
        reasoning_effort="minimal",
    ),
    "control-official": lambda: RequestOptions(
        timeout_seconds=300.0,
        max_output_tokens=262144,
        token_parameter="max_tokens",
        reasoning_effort="minimal",
    ),
    "treatment": lambda: RequestOptions(
        timeout_seconds=300.0,
        max_output_tokens=262144,
        token_parameter="max_tokens",
        thinking="disabled",
    ),
}
PACKETS = {
    "base-7critical": "char:5246-5537",
    "NT-I06": "char:1393-1655",
    "NT-I41": "char:5055-5071",
}
ITEMS_ATTEMPTS = 2  # 1 attempt + 1 automatic retry (run-1 lost packets at retries=0)
THROTTLE_SECONDS = 20
BUDGET_CALLS_MAX = 9  # 3 packets x 2 attempts


def extraction_config(arm: str) -> ExtractionConfig:
    result = load_extraction_config(dotenv_path=REPO_ROOT / ".env", options=ARM_OPTIONS[arm]())
    result.require_profile()
    return result


def subset_snapshot(parent: EvidenceSnapshot, locator: str) -> EvidenceSnapshot:
    """Rebuild a one-unit snapshot with the parent's own identity algorithm."""
    units = [unit for unit in parent.units if unit.locator == locator]
    if len(units) != 1:
        raise SystemExit(f"locator {locator}: expected 1 unit, found {len(units)}")
    locators = {locator}
    gaps = tuple(gap for gap in parent.gaps if gap.locator in locators)
    parser_versions = dict(parent.parser_versions)
    identity = SnapshotIdentityInput(
        source_id=parent.source_id,
        build_id=parent.build_id,
        publication_generation=parent.publication_generation,
        parser_versions=parser_versions,
        unit_identities=(_identity_of(units[0]),),
    )
    subset = EvidenceSnapshot(
        snapshot_id=_canonical_hash(identity.model_dump(mode="json")),
        source_id=parent.source_id,
        build_id=parent.build_id,
        publication_generation=parent.publication_generation,
        parser_versions=parser_versions,
        units=(units[0],),
        gaps=gaps,
        identity_input=identity,
    )
    subset.verify_identity()
    return subset


def save(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def prep(arm: str) -> list[dict[str, Any]]:
    parent = EvidenceSnapshot.model_validate_json(
        json.dumps(json.loads(PARENT_PLAN.read_text(encoding="utf-8"))["snapshot"])
    )
    parent.verify_identity()
    config = extraction_config(arm)
    runner_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out = ARM_OUTPUT[arm]
    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for name, locator in PACKETS.items():
        snapshot = subset_snapshot(parent, locator)
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        slots = build_candidate_slots(document, build_material_structure(document))
        target = out / name
        target.mkdir(exist_ok=True)
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        plan: BatchPlan | None = None
        slot_count = len(slots)
        if slot_count == 0:
            note = "0 candidate slots in this packet — no model call needed"
        else:
            plan = plan_batch(
                snapshot,
                config=config,
                max_attempts=ITEMS_ATTEMPTS,
                role_max_attempts={"claims": 0, "material_items": ITEMS_ATTEMPTS},
                relations_enabled=False,
                deadline_epoch=time.time() + 3600,
            )
            save(target / "plan.json", plan.model_dump(mode="json"))
            note = "frozen"
        freeze = {
            "packet": name,
            "locator": locator,
            "unit_id": snapshot.units[0].unit_id,
            "snapshot_id": snapshot.snapshot_id,
            "slot_count": slot_count,
            "items_attempts_max": ITEMS_ATTEMPTS,
            "automatic_retries": ITEMS_ATTEMPTS - 1,
            "throttle_seconds": THROTTLE_SECONDS,
            "budget_calls_max": BUDGET_CALLS_MAX,
            "relations_enabled": False,
            "output_enters_scoring": arm == "treatment",
            "arm": arm,
            "request_options": str(config.require_profile().options),
            "model": config.require_profile().model,
            "profile_sha256": config.require_profile().fingerprint,
            "runner_sha256": runner_sha,
            "parent_plan": str(PARENT_PLAN.relative_to(REPO_ROOT)),
        }
        save(target / "freeze.json", freeze)
        entries.append(
            {
                "packet": name,
                "locator": locator,
                "slots": slot_count,
                "will_call": slot_count > 0,
                "attempts_max": ITEMS_ATTEMPTS if slot_count else 0,
                "note": note,
            }
        )
    save(
        out / "prep-manifest.json",
        {
            "arm": arm,
            "model": config.require_profile().model,
            "request_options": str(config.require_profile().options),
            "model_calls_so_far": 0,
            "single_variable": (
                "model only vs run-1; treatment arm adds the DECLARED doubao thinking=disabled "
                "switch (user-authorized 2026-10-13) — control uses gate-28 frozen options verbatim"
            ),
            "output_enters_scoring": arm == "treatment",
            "packets": entries,
            "max_total_calls": BUDGET_CALLS_MAX,
        },
    )
    return entries


def live(arm: str) -> int:
    config = extraction_config(arm)
    calls = 0
    results: list[dict[str, Any]] = []
    for index, name in enumerate(PACKETS):
        target = ARM_OUTPUT[arm] / name
        if not (target / "plan.json").exists():
            results.append({"packet": name, "skipped": "0 slots"})
            continue
        plan = BatchPlan.model_validate_json((target / "plan.json").read_text(encoding="utf-8"))
        existing = target / "summary.json"
        if existing.exists():
            prior = json.loads(existing.read_text(encoding="utf-8"))
            if prior.get("plan_consistent"):
                results.append({"packet": name, "resumed": "already succeeded, no re-spend"})
                continue
        if index and calls:
            time.sleep(THROTTLE_SECONDS)
        result = execute_batch(plan, store_root=target / "store", allow_model=True, config=config)
        save(target / "summary.json", result.model_dump(mode="json"))
        # LedgerAttempt carries call identity only (no role/status); task status lives on
        # ledger.tasks (crash of 2026-10-13: LedgerAttempt has no .role).
        attempts = [
            {
                "attempt_number": a.attempt_number,
                "execution_status": a.execution_status,
                "request_model": a.request_model,
                "response_model": a.response_model,
                "usage": a.usage,
            }
            for a in result.ledger.attempts
        ]
        tasks = [
            {
                "task_id": t.task_id[:20],
                "role": t.role,
                "execution_status": t.execution_status,
                "protocol_status": t.protocol_status,
                "quality_status": t.quality_status,
                "publication_status": t.publication_status,
                "error_codes": t.error_codes,
            }
            for t in result.ledger.tasks
        ]
        calls += len(result.ledger.attempts)
        results.append(
            {
                "packet": name,
                "plan_consistent": result.plan_consistent,
                "findings": list(result.findings),
                "attempts": attempts,
                "tasks": tasks,
            }
        )
        if calls > BUDGET_CALLS_MAX:
            raise SystemExit(f"budget guard: {calls} calls > {BUDGET_CALLS_MAX}; aborting")
    save(
        ARM_OUTPUT[arm] / "arm-run.json",
        {
            "arm": arm,
            "model": config.require_profile().model,
            "request_options": str(config.require_profile().options),
            "model_calls": calls,
            "budget_cap": BUDGET_CALLS_MAX,
            "output_enters_scoring": arm == "treatment",
            "results": results,
        },
    )
    print(json.dumps({"calls": calls, "results": results}, ensure_ascii=False, indent=1))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=sorted(ARM_OUTPUT), required=True)
    parser.add_argument("--live", action="store_true", help="execute model calls (spends budget)")
    args = parser.parse_args()
    if not args.live:
        entries = prep(args.arm)
        print(json.dumps(entries, ensure_ascii=False, indent=1))
        return
    if not (ARM_OUTPUT[args.arm] / "prep-manifest.json").exists():
        raise SystemExit("run prep first (zero-call)")
    raise SystemExit(live(args.arm))


if __name__ == "__main__":
    main()
