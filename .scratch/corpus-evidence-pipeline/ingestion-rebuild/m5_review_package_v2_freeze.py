"""生成 i0c-r16 冻结快照：M5 复核包 v2（锚点改绑 i0c-r15 + 链级块纳管）。

背景：I2 全链路复核整改（RM-FC-0～8）产生 i0c-r15，变更了 engine/clean/cli/read_pg 的实现字节
并新增 gaps.py；M5 复核包 v1 的 r13 锚点与 import-smoke 固定计数随之过时。申请方按 §10 修订
复核包（v2），**必须**建新冻结修订重绑该包字节，否则矩阵前置门 freeze-validator 会正确地拦住
（实测：v2 包字节未冻结时前置门 exit=1，绑定零漂移门生效）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘（r16→r15→…）。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/m5_review_package_v2_freeze.py
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

SNAPSHOT_ID = "i0c-r16"
PARENT_ID = "i0c-r15"
M5_DIR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review"

GROUPS: dict[str, tuple[str, ...]] = {
    "review_package": (
        f"{M5_DIR}/README.md",
        f"{M5_DIR}/run_matrix.sh",
        f"{M5_DIR}/verify_matrix.py",
        f"{M5_DIR}/cross-check.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "freeze_generator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/m5_review_package_v2_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R16 FREEZE FAILED: {message}")
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
        "revision": "r16",
        "phase": "i0c",
        "task": (
            "M5 review package v2: re-anchor to i0c-r15 (I2 full-chain remediation), "
            "add chain-level evidence blocks, import-smoke judged by import closure"
        ),
        "binding": binding,
        "corrections": {
            "m5_review_package_v2": (
                "M5 复核包 v2：复核对象由 i0c-r13 改绑 i0c-r15（RM-FC 整改变更了实现字节）；"
                "freeze-hashes 纳入 r14/r15；新增 i2-fullchain-probes（12）与 i2-gap-dispositions（13）"
                "两块（RM-FC-8 链级纳管）；import-smoke 判据由固定 358/358 改为「导入闭合」正则；"
                "I2_CHANGED_FILES 增 gaps.py/clean.py/缺口测试；§5/cross-check 增 X11—X15。"
            ),
            "i0c-r15": "I2 全链路复核整改（F1—F4 / RM-FC-0～8）为本次复核对象修订。",
            "RM-FC-8": "回路纳管（链级块进放行前置）+ 重冻 + 台账回填的收口项。",
            "gate_rehearsal": (
                "实测：v2 包字节未冻结时，矩阵前置门 freeze-validator 以 "
                "『review_package 4 文件哈希失配』exit=1 拦住——绑定零漂移门有效；"
                "该次被拦产物保留在 "
                "audits/20260918-m5-review/evidence-aborted-r15-pregate/（不作复核证据）。"
            ),
        },
        "notes": [
            "仅绑定复核包与校验/生成器；实现/测试/文档绑定由 i0c-r15 持有，本修订不改其字节。",
            "矩阵预期未放宽：六族 17/18/8/5/19/4、i28-i24 探针 6、i1 业务 188、guard 19 全部保持；"
            "新增两块为链级契约面（12 + 13）。",
            "生产库 I4 前零写入；矩阵只对 i2_sandbox_corpus 运行。",
        ],
        "m5_declaration": "not_declared（本修订仅为复核备料重冻；放行由复核结论 + U 签认给出）",
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
