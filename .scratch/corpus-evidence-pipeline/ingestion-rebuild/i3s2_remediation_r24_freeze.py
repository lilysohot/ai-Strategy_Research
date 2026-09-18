"""生成 i0c-r24 冻结快照：I3-2 补料（二轮复核 A1—A5 整改：审批链路 + 覆盖账 + 角色与展示）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r24→r23→…→i0a5）与绑定。历史快照 r1..r23 字节不改写。

本修订只绑补料产物、共享文本层、裁决应用器、本轮归档件、验证器与台账；
**不得**出现 ``plugins/``／``tests/``／守卫绑定（本轮没碰实现字节：评分器仍是 r21 绑定）。

冻结前置（脚本内强制，任一不满足即拒绝）：
- 候选 ``rule_rev == evidence-mapping-5``；
- 输入哈希与冻结 query/source gold 实际字节一致；
- 自检 ``self_consistency.failed == 0`` 且 ``regression_probes.failed == 0``；
- 批准件尚不存在、``approval-report.json`` 为 ``stage=no_decisions`` 且 ``ready is False``
  （候选阶段）；一旦有人裁决并放行，必须另建修订并同步台账，不得复用本快照。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_remediation_r24_freeze.py
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

SNAPSHOT_ID = "i0c-r24"
PARENT_ID = "i0c-r23"

TOOLING = (
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_textutil.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_apply_decisions.py",
)
ASSETS = (
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-adjudication.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/approval-report.json",
)
# r23 绑定的字节，本轮被同名文件覆盖，归档保留（write-once 留痕）
ARCHIVES = (
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates-v4.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review-v4.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-adjudication-v1.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification-v2.json",
)

GROUPS: dict[str, tuple[str, ...]] = {
    "i3_2_tooling": TOOLING,
    "i3_2_assets": ASSETS,
    "i3_2_archive": ARCHIVES,
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
    print(f"I0C-R24 FREEZE FAILED: {message}")
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

    candidates = json.loads(
        (BASE / "i3-2/evidence-targets-candidates.json").read_text(encoding="utf-8")
    )
    verification = json.loads(
        (BASE / "i3-2/evidence-targets-verification.json").read_text(encoding="utf-8")
    )
    report = json.loads((BASE / "i3-2/approval-report.json").read_text(encoding="utf-8"))
    if candidates.get("rule_rev") != "evidence-mapping-5":
        fail(f"候选规则版本不是 evidence-mapping-5：{candidates.get('rule_rev')!r}")
    for key, rel in (
        ("query_gold", "query-gold-frozen.jsonl"),
        ("source_gold", "source-gold-frozen.jsonl"),
    ):
        declared = (candidates.get("inputs") or {}).get(key, {}).get("sha256")
        actual = digest(BASE / rel)
        if declared != actual:
            fail(f"候选声明的 {key} 输入哈希与冻结件实际字节不一致（{declared} != {actual}）")
    if verification.get("self_consistency", {}).get("failed") != 0:
        fail("自洽往返存在失败项；不得据未过自检冻结候选")
    probes = verification.get("regression_probes", {})
    if probes.get("failed") != 0:
        fail("独立反例探针存在失败项；不得据未过探针冻结候选")
    if verification.get("completeness_gate", {}).get("stage") != "no_decisions":
        fail("完整性门阶段不是 no_decisions；说明已有裁决/审批件，须另建修订")
    if report.get("ready") is not False or report.get("stage") != "no_decisions":
        fail("approval-report 显示已放行；候选阶段必须 ready=false / stage=no_decisions")
    if (BASE / "i3-2/evidence-targets-decisions.json").is_file():
        fail("工作区已存在审批件；本快照是未裁决候选，须另建修订")
    if (BASE / "i3-2/evidence-targets-approved.json").is_file():
        fail("工作区已存在批准投影；不得把它绑进未裁决候选快照")

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
        "revision": "r24",
        "phase": "i0c",
        "task": (
            "I3-2 material prep remediation round 2 (independent review A1-A5): adjudication "
            "artifact -> approved projection -> completeness gate with per-kind validation, "
            "value/qualification facets registered per segment, anchor adequacy with uncovered "
            "terms, required/supplementary/suggested roles; candidates only, no gold freeze"
        ),
        "binding": binding,
        "corrections": {
            "I3-2_adjudication_review_remediation": (
                "依据 audits/20260918-i32-adjudication-review/review.md（A1—A5）整改："
                "A1 完整性门不再看候选 adjudication.status（改它不会开门）；"
                "A2 新增裁决应用器与审批件/批准投影/门三段路径（含 input 哈希过期检查）；"
                "A3 机器锚点给 adequacy/uncovered_terms 与面级 union 缺口，partial 必须改选/补标/residual；"
                "A4 数值与限定按段并行登记（含数字子句里的限定不再漏账）；"
                "A5 角色改 required/supplementary/suggested（不再称「可替代」）、"
                "裁决单直接展示 source_coverage 锚点、清除旧批次数字、写清四类待填项。"
            ),
            "evidence_mapping_rule_rev": (
                "规则 evidence-mapping-5 + 共享文本层 i3s2_textutil.py：分号/句号切子句，"
                "子句既有数值又有标记时再按逗号拆段；字母边界数值匹配 + 数值等价（Decimal 归一）；"
                "重复出现不去重；必需=最小覆盖集合（IDF 加权 + 未占用优先）；"
                "定性要件给 note_ref/内容重叠锚点并标覆盖度；答案侧口径记 answer_constraints。"
            ),
            "approval_path": (
                "evidence-targets-decisions.json → i3s2_apply_decisions.py → "
                "evidence-targets-approved.json + approval-report.json。门逐项核对要件裁决、"
                "整题验收、负例覆盖、来源状态澄清、锚点覆盖度与输入哈希；"
                "驳回不删除原题要求，补标注须先有新 source-gold 版本。"
            ),
            "completeness_gate": (
                "自检三段：self_consistency 0 failed；regression_probes 16/16（含审批门反例："
                "状态翻转/空审阅人/要件缺项/负例未确认/审批过期不得开门，完整审批件可开门并产出投影）；"
                "completeness_gate = no_decisions / ready=false（候选阶段正确状态）。"
            ),
            "human_adjudication": (
                "裁决单四类待填：要件裁决 40 项、有答案题整题验收 24 题（含 machine_ready 题）、"
                "负例覆盖 6 题、来源槽位状态澄清 1 项（macro-039-claim-001）。机器已批准 0 项。"
            ),
        },
        "notes": [
            "历史快照 r1..r23 保留字节，不追改；r23 绑定的候选/核对单/裁决单/验证报告"
            "已归档为 -v4/-v4/-v1/-v2 并在本修订 i3_2_archive 组绑定。",
            "I3-0 复核整改（r21）仍在等待复核确认闭环与 U 签认；I3-2 完整任务（阈值/关键题/负例/"
            "旧基线映射与评分器冻结）未完成，本修订只交补料候选、裁决单与审批链路。",
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
