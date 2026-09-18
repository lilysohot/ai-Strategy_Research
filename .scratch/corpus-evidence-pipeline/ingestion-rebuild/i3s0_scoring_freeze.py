"""生成 i0c-r19 冻结快照：I3-0 三类指标评分器（scoring.py）交付 + 合成检验 + i3 守卫阶段。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r19→r18→…→i1-r4→i0a5）与绑定。历史快照 r1..r18 字节不改写。

本修订是**纯新增**：implementation 组只允许出现 plugins/corpus/scoring.py，
validate_i0c_freeze.py 的 r19 块强制该不变量（越界即失败）。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s0_scoring_freeze.py
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

SNAPSHOT_ID = "i0c-r19"
PARENT_ID = "i0c-r18"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": ("plugins/corpus/scoring.py",),
    "tests": ("tests/test_corpus_scoring.py",),
    "guard": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-guard-report.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3_guard_selfcheck.py",
    ),
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
    print(f"I0C-R19 FREEZE FAILED: {message}")
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

    guard_report = json.loads(
        (ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-guard-report.json")
        .read_text(encoding="utf-8")
    )
    if not guard_report.get("passed") or guard_report.get("phase") != "i3":
        fail("i3 守卫自检报告未通过或阶段不符；不得据未过报告冻结")

    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "revision": "r19",
        "phase": "i0c",
        "task": (
            "I3-0: deterministic scorer for DocRecall@k / QuestionPass@k / EvidencePass@k "
            "(denominators, any/all, negative cases, critical-question veto) + synthetic tests "
            "+ i3 guard phase; add-only revision"
        ),
        "binding": binding,
        "corrections": {
            "I3-0": (
                "I3-0 交付：plugins/corpus/scoring.py（架构 §12.3 三类指标唯一落点，纯标准库，"
                "无模型/网络/PG/时钟/I-O）+ tests/test_corpus_scoring.py（31 合成用例）+ i3 守卫阶段；"
                "本轮为纯新增，未改任何既有实现字节。"
            ),
            "DocRecall": (
                "DocRecall@k 逐题 |Top-k∩相关|/|相关| 后按类宏平均；非空相关集为分母，"
                "空集按缺必需输入阻断并计入未通过；负例不进召回分母。"
            ),
            "QuestionPass": (
                "QuestionPass@k 按冻结 any/all：any=至少一份相关文档进 Top-k；all=全部进 Top-k，"
                "相关集大于 k 时判不可满足并阻断（另设 top-k，不删目标凑 Recall@5）。"
            ),
            "EvidencePass": (
                "EvidencePass@k 逐目标判定：证据只取自前 k 名文档，需 verified=True 且 quote 逐字包含"
                "（code point）且 locator token 子集匹配；全目标满足才算该题通过；越界证据记账"
                " evidence_outside_top_k，未核验证据记账 evidence_unverified。"
            ),
            "evidence_targets_absent": (
                "冻结 query-gold 目前只有散文 evidence_requirement，缺机器可读证据目标；评分器把该缺口"
                "显式化为 missing_required_input:<qid>:evidence_targets_absent（计入 EvidencePass 分母为未通过），"
                "并有答案题默认 evidence_required=True——必须显式证据决议，不允许“没写目标”静默退出分母。"
            ),
            "M5_F3_registered": (
                "M5 复核报告 F3（validate_i1_freeze.py 对当前工作区 13 项失配，P3，既有状态）本轮只登记未修，"
                "登记于 tasks.md §0/§3.6 与总台账 I3-0 条目，建议随 I3 前置修订理顺。"
            ),
            "thresholds": (
                "门槛用 Fraction 精确比较（默认 19/20）：10 题 95% 即要求 10/10，不做 float 近似；"
                "零分母/未定义指标、低于门槛、缺必需输入、误报与伪造引用超限均落机读 blockers。"
            ),
        },
        "notes": [
            "历史快照 r1..r18 保留字节，不追改；本修订为 I3-0 的纯新增冻结。",
            "证据：普通环境 tests/test_corpus_scoring.py 31 passed；i3 守卫 env 31 passed；"
            "守卫自检 cases=24 failed=0（config_sha256=655b4e1c…）；守卫自带测试 19 passed；"
            "ruff（CI 范围）+format-check 通过；pyright plugins/corpus 0 errors；"
            "import_smoke --stage 1 360/360、--stage 2 409/409。",
            "M5 已放行并经 U 签认（2026-09-18）；I3-0 按纪律不自我宣告 complete，待独立复核 + U 签认；"
            "I3-2（预期与评分器冻结）前置已满足，但须先补机器可读证据目标或显式 evidence_required=false。",
            "零模型、零 PG、零来源读取：本轮运行全部在普通环境或 i3 守卫（deny_all 网络 + read_roots 空）；"
            "生产库 I4 前零写入。",
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
