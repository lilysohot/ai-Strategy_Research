"""生成 i0c-r20 冻结快照：修正验证器 i0c-r19 块的守卫资产路径拼装（当轮未过门即发现）。

按 write-once 纪律不追改 i0c-r19 的字节，而是追加一个新修订重绑验证器与台账文字；
本修订**不得**重绑 ``plugins/``／``tests/``／``guards/i3.json`` 字节（验证器 r20 块强制）。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s0_r20_freeze.py
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

SNAPSHOT_ID = "i0c-r20"
PARENT_ID = "i0c-r19"

GROUPS: dict[str, tuple[str, ...]] = {
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "docs": (
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "docs/plan/claims-market-closed-loop-plan.md",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R20 FREEZE FAILED: {message}")
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
        "revision": "r20",
        "phase": "i0c",
        "task": (
            "fix validator i0c-r19 block guard-asset path construction (guard assets were "
            "looked up as .../guards/guards/i3.json); rebind validator + ledger text only"
        ),
        "binding": binding,
        "corrections": {
            "validator_path_fix": (
                "i0c-r19 首次过门即失败：validate_i0c_freeze.py 的 r19 块把守卫资产路径拼成 "
                ".scratch/.../guards/guards/i3.json（多一层 guards/），报 'i0c-r19 未绑定 I3 守卫资产 "
                "guards/i3.json'（exit 1）。按 write-once 不追改 r19 快照字节，改为在本修订重绑验证器；"
                "同时把 r19/r20 块与索引/血缘/收尾输出同步到 r20。"
            ),
            "scope": (
                "本修订只重绑验证器与两份台账文字：plugins/、tests/、guards/i3.json、"
                "i3-guard-report.json、i3_guard_selfcheck.py 字节一律未变（验证器 r20 块强制该不变量）。"
            ),
        },
        "notes": [
            "I3-0 交付面（评分器/测试/守卫/i3 守卫报告）仍以 i0c-r19 的绑定为准，本修订不覆盖其哈希。",
            "证据未变：scoring 测试 31 passed（普通环境与 i3 守卫 env 各一次）；守卫自检 cases=24 failed=0；"
            "ruff（CI 范围）+format-check 通过；pyright plugins/corpus 0 errors；"
            "import_smoke --stage 1 360/360、--stage 2 409/409。",
            "M5 已放行并经 U 签认；I3-0 按纪律待独立复核 + U 签认；生产库 I4 前零写入。",
        ],
        "m5_declaration": (
            "released_by_U_signoff（2026-09-18）；I3-0 delivered_pending_independent_review"
        ),
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
