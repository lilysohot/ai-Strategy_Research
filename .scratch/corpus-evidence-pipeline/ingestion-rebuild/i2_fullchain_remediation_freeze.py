"""生成 i0c-r15 冻结快照：I2 全链路独立复核整改（F1—F4 / RM-FC-0～8）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r15→r14→…→i1-r4→i0a5）与绑定。历史快照 r1—r14 字节不改写。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2_fullchain_remediation_freeze.py
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

SNAPSHOT_ID = "i0c-r15"
PARENT_ID = "i0c-r14"
AUDIT = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/preparation/gaps.py",
        "plugins/corpus/preparation/clean.py",
        "plugins/corpus/preparation/engine.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/cli.py",
    ),
    "tests": ("tests/test_corpus_gap_dispositions.py",),
    "docs": (
        "docs/plan/corpus-ingestion-rebuild-architecture.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "docs/plan/claims-market-closed-loop-plan.md",
    ),
    # 复核方证据（write-once，本轮不修改）：回路探针即 I3-7 复用的 E2E 基线来源。
    "review_evidence": (
        f"{AUDIT}/review.md",
        f"{AUDIT}/remediation-checklist.md",
        f"{AUDIT}/test_fullchain_probes.py",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "freeze_generator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2_fullchain_remediation_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R15 FREEZE FAILED: {message}")
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
        "revision": "r15",
        "phase": "i0c",
        "task": (
            "I2 full-chain independent review remediation (F1-F4 / RM-FC-0..8): gap "
            "disposition + coordinates, machine-readable gaps in check/status, coverage scoped"
        ),
        "binding": binding,
        "corrections": {
            "RM-FC-0": (
                "裁定（写入架构 §7.3/§9）：缺口分级 = A（disposition 默认分级表）"
                "+ C（缺口坐标化）组合；F4 命名以实现为准（corpus-status --build）。"
                "缺口台账形状不变（gap_regions/oversized_chunks 两键），缺口身份仍为 "
                "issue:<code>:<location>。"
            ),
            "RM-FC-1": (
                "F1：engine._verify_publication_ready 由「缺口非空恒拒」改为按 gaps 裁决——"
                "blocking 拒（文案保留 gap_regions）、acknowledged/可证范围外放行；"
                "acknowledged 缺口的依据（gap_policy_rev）与记录人（operator）写入 PUBLISHED "
                "job 检查点。"
            ),
            "RM-FC-2": (
                "F1-C：preparation/gaps.py 新增——码表/默认分级/恢复路径唯一来源；"
                "clean.CleanRegion 承载结构化坐标（page/element/char/unlocatable）。"
            ),
            "RM-FC-3": (
                "F2：corpus-check 被拒时输出结构化 gaps/gap_summary/recovery（原实测红转绿）。"
            ),
            "RM-FC-4": (
                "F2：corpus-status 输出 gaps/gap_summary/recovery 与缺口感知的 next（原实测红转绿）。"
            ),
            "RM-FC-5": (
                "F3：read_pg.DocumentEvidence/fetch_document 写明 \"\\n\" 拼接语义（非源文件字节还原），"
                "架构 §7.2 同步登记。"
            ),
            "RM-FC-6": ("F4：架构 §9 CLI 表 --job 用词作废，改为 --build（与实现一致）。"),
            "RM-FC-7": (
                "提升项：corpus-plan 增加只读可发布性预检（同一分级实现；无 scope ⇒ 只可能更严）；"
                "coverage 补 published_with_gaps 计数与 gap_regions_present 理由码，"
                "processing 如实降为 scoped。"
            ),
            "F1": "见 RM-FC-1/RM-FC-2（§7.3 scoped 不可达已解除）。",
            "F2": "见 RM-FC-3/RM-FC-4。",
            "F3": "见 RM-FC-5。",
            "F4": "见 RM-FC-6。",
        },
        "notes": [
            "回路基线：audits/20260918-i2-fullchain-review 12 项探针 10 passed/2 failed → 12 passed"
            "（2 红即 F2 的两条契约断言）。",
            "官方 I2 六族真库门仍 71 passed 零 skip（未因新增缺口路径放宽；未修改六族测试文件）。",
            "新增常驻回归 tests/test_corpus_gap_dispositions.py（真库 13 passed 零 skip）；"
            "普通环境非 PG 语料全量 595 passed / 5 skipped。",
            "生产库 I4 前零写入；真库动作仅限 i2_sandbox_corpus 的 corpus schema。",
            "M5 复核包（r14）的对象锚点应改绑 i0c-r15：本修订变更了 engine/cli/read_pg/clean 的实现字节。",
            "既有状态（非本修订引入）：freezes/validate_i1_freeze.py 对 i1-r3 的工作区绑定自 I0-C/I2 起已失配，"
            "本修订未扩大该面；M5 复核矩阵只要求 validate_i0c_freeze.py。",
        ],
        "m5_declaration": "not_declared（本轮整改不改 M5 结论；待独立复核 + U 签认）",
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
