"""生成 i0c-r22 冻结快照：I3-2 补料（证据目标候选 + 往返验证 + 待裁决清单）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r22→r21→…→i1-r4→i0a5）与绑定。历史快照 r1..r21 字节不改写。

本修订**只绑补料产物与台账**（另加重绑验证器）：validate_i0c_freeze.py 的 r22 块强制
不得出现 ``plugins/``／``tests/`` 越界绑定。候选未被裁决前不是正式金标。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_freeze.py
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

SNAPSHOT_ID = "i0c-r22"
PARENT_ID = "i0c-r21"

GROUPS: dict[str, tuple[str, ...]] = {
    "i3_2_assets": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification.json",
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
    print(f"I0C-R22 FREEZE FAILED: {message}")
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

    verification = json.loads(
        (ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/"
         "evidence-targets-verification.json").read_text(encoding="utf-8")
    )
    if verification.get("summary", {}).get("failed") != 0:
        fail("往返验证存在失败项；不得据未过验证冻结候选")

    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "revision": "r22",
        "phase": "i0c",
        "task": (
            "I3-2 material prep: machine-readable evidence targets mapped from I0A-4 human "
            "annotations (rule evidence-mapping-3) + round-trip verification through the I3-0 "
            "scorer + reconciliation sheet for U adjudication; candidates only, no gold freeze"
        ),
        "binding": binding,
        "corrections": {
            "I3-2_evidence_targets_candidates": (
                "补料候选（A 侧机器建议，非人工金标）：30 题 → mapped 20 ／ partial 1 ／ "
                "needs_human 3 ／ 负例 6，候选证据目标 60 条；证据全部取自 I0A-4 人工标注槽位"
                "（reviewer=xyl），不读原文正文、不调模型、不触 PG。"
            ),
            "evidence_mapping_rule_rev": (
                "规则 evidence-mapping-3：数字 token 边界匹配（修复 v1 子串误命中，如 20 命中 2026）、"
                "页码提示剥离另存、同 (槽位,item) 多 token 合并为一个 target、无强 token 的定性题不猜"
                "（needs_human + item 预览）、target 超护栏降级 needs_human、负例显式 "
                "evidence_required=false。v1/v2 归档保留并在 supersedes 登记缺陷。"
            ),
            "verification_roundtrip": (
                "i3s2_verify_candidates.py：gold_from_records 接受『冻结金标 + 候选目标』合成记录；"
                "30/30 项检查通过——mapped/partial 题在合成观测下三项全过（候选自洽），"
                "3 道待人工题按设计 evidence_targets_absent 阻断整轮（各类 EvidencePass 87.5%、"
                "关键题 company-008 未过），负例空命中无按误报与伪造引用；合成观测仅证明候选自洽，"
                "不代表真实链路可达。"
            ),
            "reconciliation_points": (
                "U 待裁决 4 项：①3 道定性题（company-008/industry-006/macro-004）人工指定证据目标；"
                "②company-004 的 13.40 未命中 token（缺标注或需人工指定）；"
                "③EvidencePass 分母口径（逐 item 严 60 条 vs 槽位聚合宽）；"
                "④6 道负例 evidence_required=false 的批准。裁决前候选不得当正式金标，"
                "也不得先跑候选业务结果再补答案。"
            ),
        },
        "notes": [
            "历史快照 r1..r21 保留字节，不追改。本修订不改任何实现/测试/守卫字节（验证器 r22 块强制）。",
            "I3-0 复核整改（r21）仍在等待复核确认闭环与 U 签认；I3-2 完整任务（阈值/关键题/负例/"
            "旧基线映射与评分器冻结）未完成，本修订只交补料候选。",
            "M5 报告 F3（validate_i1_freeze.py 既有失配）仍未修，已登记。",
            "零模型、零 PG、零来源正文读取；生产库 I4 前零写入。",
        ],
        "m5_declaration": (
            "released_by_U_signoff（2026-09-18）；"
            "I3-0 remediation_pending_confirmation；I3-2 material_candidates_pending_adjudication"
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
