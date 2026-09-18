"""生成 i0c-r13 冻结快照：I2-6（authority + cli_isolation）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r13→r12→…→i1-r4→i0a5）与绑定。历史快照字节不改写。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s6_freeze.py
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

SNAPSHOT_ID = "i0c-r14"
PARENT_ID = "i0c-r13"

GROUPS: dict[str, tuple[str, ...]] = {
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
    "review_package": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/README.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/run_matrix.sh",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/verify_matrix.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/cross-check.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"M5-REVIEW FREEZE FAILED: {message}")
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
        "revision": "r14",
        "phase": "i0c",
        "task": (
            "M5 independent review package: review outline + release-condition checklist, "
            "18-block command matrix with fail-fast preflight and JUnit-exact verification, "
            "cross-check checklist X1-X10, self-testing matrix verifier"
        ),
        "binding": binding,
        "corrections": {
            "m5_review_package": (
                "M5 独立复核材料已备（申请方备料，非复核结论）：README.md（复核对象/版本锚点/"
                "放行条件核对清单 A—E/命令矩阵与预期/已知口径/发现模板/纪律与判定输出）、"
                "run_matrix.sh（18 块：前置门 freeze-validator+freeze-hashes+target-guard+"
                "guard-selfcheck 失败即停；行为矩阵 publication/repository/authority/cli_isolation/"
                "consumers/cli_pg/probes/i1-business/guard-tests 全 JUnit 出证；静态 ruff/pyright/"
                "import_smoke；运行后绑定零漂移门 + 哈希留痕；末尾汇总核对）、"
                "cross-check.md（X1 哈希与血缘、X2 绑定逐文件复算与漏绑核查、X3 用例数一致、"
                "X4 守卫对抗探针、X5 write-once、X6 legacy 双向 fail-closed、X7 同快照不变量、"
                "X8 零模型子进程、X9 目标 fail-closed、X10 装置自证）、verify_matrix.py"
                "（退出码+JUnit 计数+日志命中+自检 JSON 自动判定，含 --self-test 篡改自证）。"
                "申请方演练：18 块 MATRIX OK、SELFTEST_OK（篡改副本被判 2 项 MISS）、"
                "write-once 拒绝实测 exit 2/1；演练证据在临时目录已删除，不构成证据。"
                "M5 仍待独立复核 + U 签认，本修订不宣告 M5。"
            )
        },
        "notes": [
            "i0c-r9～r13 保留历史字节，不追改；本修订仅登记复核材料与台账/清单指向。",
            "复核对象 = i0c-r13（parent=i0c-r12）；复核包内所有预期计数与哈希均绑定该时点。",
            "I2 全部完成；M5 技术门条件已齐，按纪律待独立复核 + U 签认。",
            "生产库 I4 前零写入；复核包不含任何凭据，DSN 由复核人环境变量传入。",
        ],
        "m5_declaration": "conditions_met_pending_review（复核材料已备 i0c-r14；仍待独立复核 + U 签认）",
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
