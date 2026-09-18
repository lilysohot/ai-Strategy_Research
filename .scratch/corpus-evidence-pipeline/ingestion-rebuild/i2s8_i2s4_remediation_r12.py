"""生成 i0c-r11 冻结快照：I2-8 / I2-4 独立复核整改（F1—F11 / RM-I28-0～13）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r11→r10→…→i1-r4→i0a5）与绑定。历史快照 r9/r10 字节不改写。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s8_i2s4_remediation_freeze.py
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

SNAPSHOT_ID = "i0c-r12"
PARENT_ID = "i0c-r11"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/tools/data_coverage.py",
    ),
    "tests": (
        "tests/test_data_coverage.py",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R12 FREEZE FAILED: {message}")
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
        "revision": "r12",
        "phase": "i0c",
        "task": (
            "i0c-r11 follow-up: data_coverage coverage_getter result narrowed to dict "
            "(pyright reportArgumentType fix); no behaviour change"
        ),
        "binding": binding,
        "corrections": {
            "type_fix": (
                "i0c-r11 后仅一处类型收窄：data_coverage 把 coverage_getter 返回值"
                "（object）显式收窄为 dict 再赋给 research_coverage（pyright "
                "reportArgumentType 1 项），行为不变；随本修订重绑该文件。"
            )
        },
        "notes": [
            "i0c-r9/r10 保留历史字节，不追改；本修订登记复核整改后的实现/测试/文档。",
            "证据：复核探针 5 failed/1 passed → 6 passed；真库 consumers_pg(19)+cli_pg(4) 全 passed 零 skip；"
            "普通环境语料全量 425 passed/1 skipped；i1 守卫 env 188 passed。",
            "I2-8 由 partial 转 complete（整改 DoD 1—6 满足）；M5 仍 not_declared（待 I2-6 与独立复核）。",
            "生产库 I4 前零写入；真库动作仅限 i2_sandbox_corpus 的 corpus schema。",
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
    print("bindings: " + ", ".join(f"{group}={len(v)}" for group, v in binding.items()))


if __name__ == "__main__":
    main()
