"""生成 i0c-r18 冻结快照：把「报告/台账中的冻结修订标识」与 i0c-r17 对齐。

背景：i0c-r17 已冻结 M5 复核报告 + 证据面 + F1 修复字节；随后在两处补记「报告冻结修订 = i0c-r17」
（review.md 头部与总台账签认段）。按「冻结后任何字节变更都要新修订」，补记后必须建 r18 重绑。
本轮**无实现/测试/行为改动**，只重绑报告与台账。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/m5_review_signoff_r18_freeze.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
FREEZES = BASE / "freezes"
ROOT = BASE.parents[2]

SNAPSHOT_ID = "i0c-r18"
PARENT_ID = "i0c-r17"
M5 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review"

GROUPS: dict[str, tuple[str, ...]] = {
    "review_report": (f"{M5}/review.md",),
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "freeze_generator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/m5_review_signoff_r18_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R18 FREEZE FAILED: {message}")
    sys.exit(1)


def main() -> None:
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parents = {entry["snapshot_id"]: entry for entry in manifest.get("snapshots", [])}
    if PARENT_ID not in parents:
        fail(f"索引缺少父快照 {PARENT_ID}")
    if SNAPSHOT_ID in parents:
        fail(f"{SNAPSHOT_ID} 已存在（write-once）")
    parent_file = FREEZES / parents[PARENT_ID]["file"]
    if not parent_file.is_file() or digest(parent_file) != parents[PARENT_ID]["sha256"]:
        fail(f"{PARENT_ID} 文件字节与索引哈希不一致")

    binding: dict[str, dict[str, str]] = {}
    for group, paths in GROUPS.items():
        table: dict[str, str] = {}
        for rel in paths:
            file = ROOT / rel
            if not file.is_file():
                fail(f"绑定文件缺失: {rel}")
            table[rel] = digest(file)
        binding[group] = table

    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "revision": "r18",
        "phase": "i0c",
        "task": "record report freeze revision (i0c-r17) in review.md and the master ledger",
        "binding": binding,
        "corrections": {
            "M5_release": "M5 放行与 U 签认（同 i0c-r17）——本修订仅补记冻结修订标识。",
            "U_signoff": "U 于 2026-09-18 签认 M5 放行。",
            "report_revision": (
                "review.md 头部与总台账签认段补记「报告冻结修订 = i0c-r17」；无实现/测试/行为改动，"
                "只重绑报告与台账，保持「读到的结论 ↔ 验证的字节」可对应。"
            ),
        },
        "notes": [
            "无 plugins/ 或 tests/ 改动；r17 的证据面绑定不变（未重绑即未改字节）。",
            "冻结链：r18->r17->r16->r15->…->i0a5(M1)；validate_i0c_freeze.py 须 exit 0。",
        ],
        "m5_declaration": "released_by_U_signoff（2026-09-18；独立性偏差已登记并由 U 接受）",
        "created_at": created_at,
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": f".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/{parent_file.name}",
            "sha256": digest(parent_file),
        },
    }

    target = FREEZES / f"{SNAPSHOT_ID}.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    manifest.setdefault("snapshots", []).append(
        {
            "snapshot_id": SNAPSHOT_ID,
            "file": target.name,
            "sha256": digest(target),
            "parent_snapshot_id": PARENT_ID,
            "created_at": created_at,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{SNAPSHOT_ID} frozen: {target} sha256={digest(target)}")
    print("bindings: " + ", ".join(f"{group}={len(v)}" for group, v in binding.items()))


if __name__ == "__main__":
    main()
