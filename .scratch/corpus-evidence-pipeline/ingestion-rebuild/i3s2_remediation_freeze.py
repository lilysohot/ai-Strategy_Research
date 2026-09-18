"""生成 i0c-r23 冻结快照：I3-2 补料（独立复核 F1—F5 整改 + 人工裁决单）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r23→r22→…→i1-r4→i0a5）与绑定。历史快照 r1..r22 字节不改写。

本修订只绑补料产物、本轮归档件、裁决单、验证器与台账；
**不得**出现 ``plugins/``／``tests/``／守卫绑定（本轮没碰实现字节：评分器仍是 r21 绑定）。

冻结前置（脚本内强制，任一不满足即拒绝）：
- 候选 ``rule_rev == evidence-mapping-4``；
- 输入哈希与冻结 query/source gold 实际字节一致（防止用过期输入出包）；
- 自检 ``self_consistency.failed == 0`` 且 ``regression_probes.failed == 0``；
- ``completeness_gate.ready`` 必须为 **false**（候选阶段）；若哪天为 true，说明已人工裁决，
  必须另建修订并同步台账，不得复用本快照。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_remediation_freeze.py
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

SNAPSHOT_ID = "i0c-r23"
PARENT_ID = "i0c-r22"

ASSETS = (
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-adjudication.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification.json",
)
ARCHIVES = (
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates-v3.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review-v3.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification-v1.json",
)

GROUPS: dict[str, tuple[str, ...]] = {
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
    print(f"I0C-R23 FREEZE FAILED: {message}")
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
    if candidates.get("rule_rev") != "evidence-mapping-4":
        fail(f"候选规则版本不是 evidence-mapping-4：{candidates.get('rule_rev')!r}")
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
    if verification.get("regression_probes", {}).get("failed") != 0:
        fail("独立反例探针存在失败项；不得据未过探针冻结候选")
    gate = verification.get("completeness_gate", {})
    if gate.get("ready") is not False:
        fail(
            "completeness_gate.ready 必须为 false（候选阶段）；若已人工裁决请另建修订并同步台账"
        )
    summary = candidates.get("summary", {})
    if summary.get("adjudication_approved") != 0:
        fail("候选摘要显示已有批准题；须另建修订（本快照是未裁决候选）")

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
        "revision": "r23",
        "phase": "i0c",
        "task": (
            "I3-2 material prep remediation (independent review F1-F5): requirement coverage "
            "ledger + table cell identity in locators + required/supporting/suggested split + "
            "value-equivalence queue + per-question EvidencePass denominator contract + "
            "independent regression probes and completeness gate; still candidates, no gold freeze"
        ),
        "binding": binding,
        "corrections": {
            "I3-2_material_review_remediation": (
                "依据 audits/20260918-i32-material-review/review.md（F1—F5）整改：F1 建要求覆盖账"
                "（定性要件不自动批准，批准状态单列）；F2 表格 row/col 进 locator、cell/unit/period 进 "
                "constraints（I3-1 须由权威侧产出 token）；F3 日期掩码 + 字母边界（8230CF 不命中 8230）+ "
                "逐次出现计数 + 必需/可替代分层；F4 分母口径改为逐题并作废二选一；F5 自检拆成"
                "自洽/反例/完整性门三段。已登记人工项逐条处置见 audit 目录 remediation-checklist.md。"
            ),
            "evidence_mapping_rule_rev": (
                "规则 evidence-mapping-4：子句拆分 → 数值要件/定性要件/期间；数值 token 边界含字母；"
                "重复出现不去重；必需=覆盖全部数值要件的最小集合（IDF 加权重叠排序）；"
                "定性要件给 note_ref/内容重叠锚点并全部入队；答案侧用法约束记 answer_constraints；"
                "数值等价显式入队且不改写原文 quote。v1/v2/v3 缺陷在 supersedes 留档。"
            ),
            "evidence_pass_denominator": (
                "EvidencePass 分母 = 逐题（架构 §12.3：满足全部必需证据的题数/证据题数）；"
                "原『逐 item 60 条 vs 槽位聚合』二选一作废，item 覆盖统计只作诊断。"
                "台账与任务清单同批修正。"
            ),
            "completeness_gate": (
                "自检三段分开判定：self_consistency（模拟批准后往返）0 failed；regression_probes "
                "9/9（结构身份缺失/同值错列/漏脚注/漏条件必须失败，最小正确证据必须通过，"
                "可替代证据缺失不得判失败，型号后缀不得伪装命中，重复来源被入口拒绝，"
                "数值等价必须显式入队）；completeness_gate.ready=false（0 题获批、24 题被拦）——"
                "候选阶段的正确状态，不得把自洽往返读成补料完整。"
            ),
            "human_adjudication": (
                "新增 evidence-targets-adjudication.md：24 道正例逐项（36 项）裁决模板，"
                "含负例覆盖确认与人工状态冲突（macro-039-claim-001 的 human_basis 与 reviewer 并存矛盾）"
                "；批准件另存 evidence-targets-decisions.json，与候选分开存储。待 U 裁决。"
            ),
        },
        "notes": [
            "历史快照 r1..r22 保留字节，不追改。本修订不改任何实现/测试/守卫字节；"
            "评分器与 i3 守卫仍按 r19—r21 绑定核验。",
            "I3-0 复核整改（r21）仍在等待复核确认闭环与 U 签认；I3-2 完整任务（阈值/关键题/负例/"
            "旧基线映射与评分器冻结）未完成，本修订只交补料候选与裁决单。",
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
