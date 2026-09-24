"""r5k 落章：把 M7 二次复核 F1—F3 的实际运行证据冻结到当前字节。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/home/administrator/FrontierAgent")
WINDOW = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
HERE = ROOT / ".scratch/m7-finalize-20260924"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
PREV = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/"
        "previous-effective-bindings-r5k.json")
CODE = ["plugins/corpus/service.py"]
TESTS = [
    "tests/test_corpus_ingest_retired.py", "tests/test_corpus_evidence_pipeline.py",
    "tests/test_corpus_authority_pg.py", "tests/test_corpus_claims_interface.py",
]
RUNTIME = [
    ".scratch/m7-rereview-20260924/report.md",
    ".scratch/m7-finalize-20260924/f1_retired_evidence_writer_verify.py",
    ".scratch/m7-finalize-20260924/f1-retired-evidence-writer-verification.json",
    ".scratch/m7-finalize-20260924/g3b_isolated_restore_body_verify.py",
    ".scratch/m7-finalize-20260924/g3b-isolated-restore-body-verification.json",
    ".scratch/m7-finalize-20260924/r5k_prepare.py",
    ".scratch/m7-finalize-20260924/r5k_finalize.py",
]
BASELINE = [
    ".scratch/m7-fix-20260924/replay_battery.py",
    ".scratch/m7-fix-20260924/i37-tests-results.json",
    ".scratch/m7-fix-20260924/live_default_product.py",
    ".scratch/m7-fix-20260924/live-default.json",
    ".scratch/m7-fix-20260924/product-trace-default.json",
    ".scratch/m7-fix-20260924/g3_isolated_restore_verify.py",
    ".scratch/m7-fix-20260924/g3-isolated-restore-verification.json",
]
STATE = ["docs/plan/corpus-ingestion-rebuild-tasks.md"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    for rel in [*CODE, *TESTS, *RUNTIME, *BASELINE, *STATE, PREV, VALIDATOR]:
        if not (ROOT / rel).is_file():
            raise SystemExit(f"missing r5k binding input: {rel}")
    before = WINDOW / "before-r5k"
    prior = json.loads((ROOT / PREV).read_text(encoding="utf-8"))
    for rel, expected in prior.items():
        archived = before / rel
        if not archived.is_file() or digest(archived) != expected:
            raise SystemExit(f"archive-first mismatch: {rel}")
    parent = FREEZES / "i0c-r5j.json"
    snapshot_path = FREEZES / "i0c-r5k.json"
    if snapshot_path.exists():
        raise SystemExit(f"write-once snapshot already exists: {snapshot_path}")
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    binding = {
        "m7_rereview_code": {rel: digest(ROOT / rel) for rel in CODE},
        "m7_rereview_tests": {rel: digest(ROOT / rel) for rel in TESTS},
        "m7_rereview_runtime": {rel: digest(ROOT / rel) for rel in RUNTIME},
        "m7_reused_baseline": {rel: digest(ROOT / rel) for rel in BASELINE},
        "m7_rereview_state": {rel: digest(ROOT / rel) for rel in STATE},
        "previous_effective_bindings": {PREV: digest(ROOT / PREV)},
        "freeze_validator": {VALIDATOR: digest(ROOT / VALIDATOR)},
    }
    parent_json = json.loads(parent.read_text(encoding="utf-8"))
    snapshot = {
        "snapshot_id": "i0c-r5k",
        "revision": "r5k",
        "phase": "i0c",
        "status": "m7_rereview_closure",
        "business_accepted": True,
        "parent_snapshot": {
            "snapshot_id": "i0c-r5j",
            "path": str(parent.relative_to(ROOT)),
            "sha256": digest(parent),
        },
        "supersedes_validator_sha256": parent_json["binding"]["freeze_validator"][VALIDATOR],
        "binding": binding,
        "correction": (
            "M7 re-review closure: F1 retires corpus_evidence_runs writes fail-closed before any "
            "connection and changes extract_claims default persistence to false; F2 binds an actual "
            "isolated restore whose 290 archived historical bodies exactly match restored blocks; F3 "
            "binds this review, runners, reports, code and tests at r5k. Earlier M7 battery/default "
            "product/G3 artifacts are retained only as explicitly labelled historical baselines."
        ),
        "corrections": {
            "m7_rereview_f1_f3": "r5k closes F1 retired evidence writer, F2 historical body restore gate, "
                                  "and F3 current-version evidence binding; I5 remains out of scope."
        },
        "created_at": now,
    }
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshots"].append({
        "created_at": now,
        "file": snapshot_path.name,
        "parent_snapshot_id": "i0c-r5j",
        "sha256": digest(snapshot_path),
        "snapshot_id": "i0c-r5k",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(FREEZES / "validate_i0c_freeze.py")], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    print((proc.stdout + proc.stderr).strip()[-4000:])
    if proc.returncode:
        return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
