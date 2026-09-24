"""r5l 落章：r5k F1 测试的纯 ruff import-order 重绑。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/home/administrator/FrontierAgent")
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
WINDOW = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
TEST = "tests/test_corpus_ingest_retired.py"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
PREV = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/"
        "previous-effective-bindings-r5l.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    snapshot_path = FREEZES / "i0c-r5l.json"
    if snapshot_path.exists():
        raise SystemExit(f"write-once snapshot already exists: {snapshot_path}")
    prior = json.loads((ROOT / PREV).read_text(encoding="utf-8"))
    for rel, expected in prior.items():
        archived = WINDOW / "before-r5l" / rel
        if not archived.is_file() or digest(archived) != expected:
            raise SystemExit(f"archive mismatch: {rel}")
    parent = FREEZES / "i0c-r5k.json"
    r5k = json.loads(parent.read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    binding = {
        "ruff_rebind_test": {TEST: digest(ROOT / TEST)},
        "previous_effective_bindings": {PREV: digest(ROOT / PREV)},
        "freeze_validator": {VALIDATOR: digest(ROOT / VALIDATOR)},
    }
    snapshot = {
        "snapshot_id": "i0c-r5l", "revision": "r5l", "phase": "i0c",
        "status": "m7_rereview_lint_rebind", "business_accepted": True,
        "parent_snapshot": {"snapshot_id": "i0c-r5k", "path": str(parent.relative_to(ROOT)), "sha256": digest(parent)},
        "supersedes_validator_sha256": r5k["binding"]["freeze_validator"][VALIDATOR],
        "binding": binding,
        "correction": "Ruff I001 import-order normalization only; r5k F1-F3 code and runtime evidence remain unchanged.",
        "created_at": now,
    }
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshots"].append({"created_at": now, "file": snapshot_path.name,
                                  "parent_snapshot_id": "i0c-r5k", "sha256": digest(snapshot_path),
                                  "snapshot_id": "i0c-r5l"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(FREEZES / "validate_i0c_freeze.py")], cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
