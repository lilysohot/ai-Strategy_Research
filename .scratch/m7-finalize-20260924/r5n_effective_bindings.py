"""计算 r5n 前三份待改文件的当前有效绑定哈希（模拟验证器 latest-wins 合并）。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"

TARGETS = {
    "docs/plan/corpus-ingestion-rebuild-tasks.md",
    "docs/plan/claims-market-closed-loop-plan.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = json.loads((BASE / "freeze-manifest.json").read_text(encoding="utf-8"))
    current: dict[str, dict[str, str]] = {}
    for entry in manifest.get("snapshots", []):
        sid = entry.get("snapshot_id", "")
        if not (sid == "i1-r4" or sid.startswith("i0c-r")):
            continue
        snap_path = BASE / entry.get("file", "")
        if not snap_path.is_file():
            continue
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        for group, items in (snap.get("binding") or {}).items():
            for rel, expected in (items or {}).items():
                for existing_group in list(current):
                    current[existing_group].pop(rel, None)
                current.setdefault(group, {})[rel] = expected
    effective = {
        rel: sha
        for group in current.values()
        for rel, sha in group.items()
        if rel in TARGETS
    }
    missing = TARGETS - set(effective)
    if missing:
        raise SystemExit(f"targets not bound in chain: {sorted(missing)}")
    # 盘面自洽校验：当前盘面哈希必须等于链上有效绑定（未漂移才允许归档回填）。
    drift = {
        rel: {"bound": sha, "disk": digest(ROOT / rel)}
        for rel, sha in effective.items()
        if digest(ROOT / rel) != sha
    }
    out = {
        "purpose": "r5n previous effective bindings (pre-change)",
        "effective_bindings": effective,
        "disk_drift": drift,
    }
    out_path = (ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                "20260923-i4-window/previous-effective-bindings-r5n.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not drift else 1


if __name__ == "__main__":
    raise SystemExit(main())
