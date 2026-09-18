"""生成 i0c-r10 冻结修订：修正 I2-8/I2-4 台账中的普通环境测试计数（423→424）。

计数差异原因：首轮普通环境跑出 1 failed（旧 coverage 契约断言）+423 passed；
按 §7.3 契约更新该断言后复跑为 424 passed / 1 skipped。文档必须与实测一致，
故追加本修订重绑这两份文档（实现/测试字节未变，不重绑）。

write-once；生成后追加 freeze-manifest 条目并由 validate_i0c_freeze.py 核验。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s8_i2s4_freeze_r10.py
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

SNAPSHOT_ID = "i0c-r10"
PARENT_ID = "i0c-r9"

GROUPS: dict[str, tuple[str, ...]] = {
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R10 FREEZE FAILED: {message}")
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

    binding = {
        group: {rel: digest(ROOT / rel) for rel in paths} for group, paths in GROUPS.items()
    }
    for group, table in binding.items():
        for rel in table:
            if not (ROOT / rel).is_file():
                fail(f"绑定文件缺失: {rel}")

    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "revision": "r10",
        "phase": "i0c",
        "task": "I2-8/I2-4 ledger count correction: ordinary-env suite is 424 passed / 1 skipped",
        "binding": binding,
        "corrections": {
            "count_correction": (
                "I2-8/I2-4 回填中的普通环境计数由 423 passed / 1 skipped 更正为 "
                "424 passed / 1 skipped：首轮 1 failed 来自 test_corpus_coverage 的旧 "
                "coverage==none 契约断言，按 §7.3 更新为新 coverage 对象断言后复跑通过，"
                "总数 425 未变（1 failed → passed）。仅文档字节变更，实现/测试不重绑。"
            )
        },
        "notes": [
            "本修订仅重绑文档与校验器；i0c-r9 的实现/测试绑定继续生效（supersession 合并核对）。",
            "I2-6 仍待执行；M5 仍 not_declared；生产库 I4 前零写入。",
        ],
        "m5_declaration": "not_declared（I2-1/2/3/4/5/7/8 完成；仍需 I2-6 与独立复核）",
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


if __name__ == "__main__":
    main()
