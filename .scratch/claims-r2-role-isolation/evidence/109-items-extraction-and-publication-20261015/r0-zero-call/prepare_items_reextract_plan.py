"""Freeze the items re-extraction plan (109 号 P1 工程缺件①): two sources, zero calls.

Re-plans the two signed non-table material-items sources **under the current code version** and
writes a write-once freeze that the executor must match byte for byte. Snapshot construction is
reused verbatim from the 28-号 freeze (imported, never edited — historical scripts stay frozen),
so the candidate input scope is the signed one and no gold reaches the model.

Fail-closed:
* the 109-号 pre-registration must be signed (``frozen_before_execution``) — "P1 签认前禁止起跑";
* the recomputed per-source batch count must not exceed the signed historical reference
  (md 10 / docx 14) — the budget authorisation was given against 24 attempts;
* every output is write-once via the shared evidence guard.

Usage:
    python prepare_items_reextract_plan.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    MATERIAL_EXTRACTOR_VERSION,
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_SELECTOR_JSONL_VERSION,
    MATERIAL_SLOT_BATCHING_VERSION,
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import plan_batch  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

PREREG = HERE / "items-reextraction-preregistration-v2.json"
AUTHORISATION = HERE / "budget-authorisation-r2.json"
FREEZE_28 = ROOT / "evidence/28-items-only-quality-gate-20261010/r0-zero-call"
OUT = HERE / "items-reextract-plan-freeze"


def _load_freeze_28() -> Any:
    """Import the 28-号 freeze module read-only: it owns the signed snapshot construction."""
    spec = importlib.util.spec_from_file_location(
        "freeze_items_only_plan_28", FREEZE_28 / "freeze_items_only_plan.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display(path: Path) -> str:
    """Repo-relative when possible; tests/dry-runs may patch these constants to temp dirs."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def signed_prereg() -> dict[str, Any]:
    prereg = load(PREREG)
    if prereg.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to freeze: pre-registration is {prereg.get('status')!r}")
    role_scope = prereg.get("role_scope")
    if role_scope != ["material_items"]:
        raise SystemExit(f"refusing to freeze: unexpected role_scope {role_scope!r}")
    auth = prereg["budget_request"]["stage_1_live_run"]["authorisation_record"]
    if auth["sha256"] != sha256(AUTHORISATION):
        raise SystemExit("refusing to freeze: pre-registration binds a different authorisation")
    return prereg


def historical_reference(prereg: dict[str, Any]) -> dict[str, int]:
    reference = prereg["budget_request"]["stage_1_live_run"]["historical_reference"]
    return {str(item["name"]): int(item["attempt_ceiling"]) for item in reference["per_execution"]}


def check_attempts(slug: str, computed: int, historical: dict[str, int]) -> None:
    expected = historical.get(f"items-{slug}")
    if expected is None:
        raise SystemExit(f"refusing to freeze: signed historical reference lacks items-{slug}")
    if computed > expected:
        raise SystemExit(
            f"refusing to freeze: {slug} recomputed {computed} batches > "
            f"signed historical {expected}（授权按 24 attempts 给出，超出须 U 另裁）"
        )


def build() -> tuple[dict[str, Any], dict[str, bytes]]:
    freeze_28 = _load_freeze_28()
    prereg = signed_prereg()
    historical = historical_reference(prereg)
    authorisation = load(AUTHORISATION)
    ceiling = authorisation["budget"]["ceiling_total_tokens"]
    if not isinstance(ceiling, int) or ceiling <= 0:
        raise SystemExit(f"refusing to freeze: authorisation ceiling {ceiling!r} is not positive")

    extraction = freeze_28.config()
    profile = extraction.require_profile()

    entries: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    for item in freeze_28.scoped_sources():
        slug = str(item["slug"])
        snapshot = item["snapshot"]
        snapshot.verify_identity()
        material_document = evidence_document_from_snapshot(snapshot, role="material_items")
        candidate_slots = build_candidate_slots(
            material_document, build_material_structure(material_document)
        )
        batches = build_candidate_slot_batches(
            candidate_slots,
            max_slots_per_batch=freeze_28.SELECTOR_MAX_SLOTS,
            max_items_per_batch=freeze_28.SELECTOR_MAX_ITEMS,
            max_estimated_tokens_per_batch=freeze_28.SELECTOR_MAX_TOKENS,
        )
        if not batches:
            raise SystemExit(f"refusing to freeze: no material-items batches for {slug}")
        attempt_ceiling = len(batches)
        check_attempts(slug, attempt_ceiling, historical)
        expected = historical[f"items-{slug}"]
        plan = plan_batch(
            snapshot,
            config=extraction,
            max_attempts=attempt_ceiling,
            role_max_attempts={
                "claims": 0,
                "material_items": attempt_ceiling,
                "material_relations": 0,
            },
            relations_enabled=False,
            enabled_roles=("material_items",),
            max_items_per_packet=freeze_28.SELECTOR_MAX_ITEMS,
            max_slots_per_batch=freeze_28.SELECTOR_MAX_SLOTS,
            max_estimated_tokens_per_batch=freeze_28.SELECTOR_MAX_TOKENS,
            material_items_protocol=MATERIAL_SELECTOR_JSONL_VERSION,
        )
        plan.verify_identity()
        counts = {
            role: sum(task.role == role for task in plan.tasks)
            for role in ("claims", "material_items", "material_relations")
        }
        if counts != {"claims": 0, "material_items": 1, "material_relations": 0}:
            raise SystemExit(f"refusing to freeze: unexpected plan shape for {slug}: {counts}")
        snapshot_bytes = (
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        plan_bytes = (
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        payloads[f"{slug}/snapshot.json"] = snapshot_bytes
        payloads[f"{slug}/plan.json"] = plan_bytes
        entries.append(
            {
                "slug": slug,
                "mode": "live_model",
                "source_id": item["source_id"],
                "snapshot_id": snapshot.snapshot_id,
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "attempt_ceiling": attempt_ceiling,
                "historical_attempt_ceiling": expected,
                "scoped_unit_count": len(snapshot.units),
                "candidate_slot_count": len(candidate_slots),
                "batch_count": attempt_ceiling,
                "protocol": MATERIAL_SELECTOR_JSONL_VERSION,
                "snapshot_file_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                "plan_file_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            }
        )

    total_ceiling = sum(int(entry["attempt_ceiling"]) for entry in entries)
    manifest: dict[str, Any] = {
        "schema_version": "items-reextract-plan-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-15",
        "purpose": (
            "109 号：在当前代码版本下冻结两源 material_items 一次全量重抽的计划；"
            "execute_items_reextract.py 是唯一执行入口，预算/签认闸门 fail-closed。"
        ),
        "prereg": {
            "path": display(PREREG),
            "sha256": sha256(PREREG),
            "stage2_gates": sorted(prereg["stage2_gates"]["gates"]),
        },
        "budget": {
            "authorisation": display(AUTHORISATION),
            "authorisation_sha256": sha256(AUTHORISATION),
            "authorisation_status": authorisation["status"],
            "ceiling_total_tokens": ceiling,
            "total_attempt_ceiling": total_ceiling,
            "historical_reference": historical,
            "note": "ceiling 在 109 号授权件（U 口谕 100 万 total_tokens）；超限判该轮无效",
        },
        "runnable": False,
        "runnable_note": (
            "缺一不可：①预注册件 frozen_before_execution ②授权件 ceiling 非空且哈希绑定 "
            "③执行者显式 --allow-model ④profile 指纹与冻结计划一致"
        ),
        "versions": {
            "items_protocol": MATERIAL_SELECTOR_JSONL_VERSION,
            "extractor": MATERIAL_EXTRACTOR_VERSION,
            "items_validation": MATERIAL_ITEMS_VALIDATION_VERSION,
            "slot_batching": MATERIAL_SLOT_BATCHING_VERSION,
            "freeze_28_script_sha256": sha256(FREEZE_28 / "freeze_items_only_plan.py"),
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
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT,
        help="round-1 evidence stays at the default; a restarted round writes a fresh freeze",
    )
    args = parser.parse_args()
    out_dir = args.out_dir if args.out_dir.is_absolute() else HERE / args.out_dir

    manifest, payloads = build()
    outputs: dict[str, bytes] = dict(payloads)
    outputs["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    if args.no_write:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("[no-write] freeze computed; nothing written.")
        return 0

    targets = {name: out_dir / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="109 号 items 重抽计划冻结件")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)
    print(f"wrote {len(outputs)} files to {out_dir}")
    print(json.dumps(manifest["budget"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
