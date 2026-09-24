"""r5m 落章：只重绑修正后的 F1 验证器语义。"""
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
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
PREV = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/"
        "previous-effective-bindings-r5m.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    target = FREEZES / "i0c-r5m.json"
    if target.exists():
        raise SystemExit(f"write-once snapshot already exists: {target}")
    parent = FREEZES / "i0c-r5l.json"
    r5l = json.loads(parent.read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    binding = {
        "previous_effective_bindings": {PREV: digest(ROOT / PREV)},
        "freeze_validator": {VALIDATOR: digest(ROOT / VALIDATOR)},
    }
    snapshot = {
        "snapshot_id": "i0c-r5m", "revision": "r5m", "phase": "i0c",
        "status": "m7_rereview_gate_clarification", "business_accepted": True,
        "parent_snapshot": {"snapshot_id": "i0c-r5l", "path": str(parent.relative_to(ROOT)), "sha256": digest(parent)},
        "supersedes_validator_sha256": r5l["binding"]["freeze_validator"][VALIDATOR],
        "binding": binding,
        "correction": "F1 checks fail-closed evidence writer behavior; it does not assert absence of a legacy table schema.",
        "created_at": now,
    }
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshots"].append({"created_at": now, "file": target.name,
                                  "parent_snapshot_id": "i0c-r5l", "sha256": digest(target),
                                  "snapshot_id": "i0c-r5m"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(FREEZES / "validate_i0c_freeze.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
