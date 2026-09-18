"""生成 i0c-r21 冻结快照：I3-0 独立复核（F1—F5）整改。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r21→r20→…→i1-r4→i0a5）与绑定。历史快照 r1..r20 字节不改写。

本修订**只改评分器与合成测试**（外加台账文字与验证器），validate_i0c_freeze.py 的 r21 块
强制该不变量：implementation 组只允许 ``plugins/corpus/scoring.py``，
且除 implementation/tests/docs/freeze_validator 外不得出现其他绑定组。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s0_r21_freeze.py
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

SNAPSHOT_ID = "i0c-r21"
PARENT_ID = "i0c-r20"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": ("plugins/corpus/scoring.py",),
    "tests": ("tests/test_corpus_scoring.py",),
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
    print(f"I0C-R21 FREEZE FAILED: {message}")
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
        "revision": "r21",
        "phase": "i0c",
        "task": (
            "I3-0 independent review remediation F1-F5: set-intersection recall + duplicate "
            "source rejection, evidence source attribution (EvidenceTarget.source_id, "
            "build_id provenance, verified must be explicit), NO_MATCH/FAILED payload rules, "
            "strict gold/observation validation shared by importer and score(), "
            "dataclass-level target invariants; overall semantics clarified"
        ),
        "binding": binding,
        "corrections": {
            "I3-0_review_remediation": (
                "依据 audits/20260918-i30-review/review.md：既有 31 项全过，独立反例 9 failed / 1 passed。"
                "本轮只改 plugins/corpus/scoring.py 与 tests/test_corpus_scoring.py（外加台账文字与验证器），"
                "不改金标、不改阈值、不删失败题、不重绑守卫/i3 守卫报告/入库实现。"
            ),
            "F1": (
                "DocRecall/QuestionPass 由条目计数改为集合运算：分子 = relevant ∩ top_sources；"
                "all 规则改为集合包含（relevant <= top_sources）；观测入口拒绝重复 source_id"
                "（chunk 必须先聚合为文档 Top-k，不得把多块当多文档）。"
            ),
            "F2": (
                "证据匹配保留 (source_id, evidence) 不压平；EvidenceTarget 新增 source_id（显式绑定），"
                "默认允许来源集 = 该题相关文档集，来源不符记 evidence_source_mismatch；"
                "RetrievedDocument 新增 build_id 身份留痕（本版不参与计分，I3-1 接线扩展跨 build 判定）；"
                "FetchedEvidence.verified 默认改为 None = 未提交核验（漏接 verify 不再自动算成功）。"
            ),
            "F3": (
                "入口拒绝 NO_MATCH + 非空 documents 的矛盾输入；FAILED 提前返回三项未通过（分母保留），"
                "并留 stale_payload_ignored:<n> 诊断。状态校验发生在算分之前。"
            ),
            "F4": (
                "导入器与 score() 共用 _validate_gold：多文档题必须显式合法声明 any/all"
                "（缺字段或非法值如 'ALL' 一律拒绝，不降级为 any）；relevant_sources 必须是字符串数组"
                "（str/bytes 不得当容器、元素必须非空 str、不强转）；critical 必须为 bool；"
                "负例题不得带 satisfy_rule；相关集与 target_id 不得重复。"
            ),
            "F5": (
                "EvidenceTarget 在 dataclass 构造期校验（空 quote 会匹配一切文本，直接拒绝）；"
                "直接构造入口与 JSON 导入器共用同一套校验，dataclasses.replace 拼出的矛盾输入同样拦住。"
            ),
            "contract_rewrite": (
                "模块 docstring 重写接口契约：文档排名的身份/去重规则、chunk→文档 Top-k 聚合要求、"
                "NO_MATCH/FAILED 语义、证据来源归属与 verified 显式提交、build_id 留痕与 I3-1 待办。"
            ),
            "overall_semantics": (
                "ScoreReport.overall 口径显式化：三项均为类间宏平均（各类等权），同时给出 "
                "question_pass_counts / evidence_pass_counts 题数汇总；判定始终按类逐项，不使用该汇总。"
                "另统一执行清单 I0—I5 行 'M5—M8 未放行' 与后文的冲突表述。"
            ),
        },
        "notes": [
            "历史快照 r1..r20 保留字节，不追改；r19 仍为 I3-0 纯新增修订，r20 为验证器路径修正，"
            "r21 为复核整改（只改评分器与测试）。",
            "证据：复核方独立反例（原文件未改）tests/../audits/20260918-i30-review/test_review_probes.py "
            "10 passed（9 红转绿 + 正控）；自身合成测试 46 passed（新增 15 项复核回归）；"
            "i3 守卫 env 46 passed；ruff（CI 范围）+format-check 通过；pyright plugins/corpus 0 errors；"
            "import_smoke --stage 1 360/360。",
            "M5 不因评分器缺陷被推翻（复核明确不推翻 M5）；本轮未改消费者/检索/取证接线，无需重验 M5 门。",
            "I3-2 仍须先补机器可读 evidence_targets 或显式 evidence_required=false；"
            "M5 报告 F3（validate_i1_freeze.py 既有失配）仍未修，已登记。",
            "零模型、零 PG、零来源读取；生产库 I4 前零写入。",
        ],
        "m5_declaration": (
            "released_by_U_signoff（2026-09-18）；"
            "I3-0 remediation_done_pending_review_confirmation_and_U_signoff"
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
