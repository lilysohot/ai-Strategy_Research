"""写 i0c-r26 冻结修订：台账回填 → r26 快照 → 索引 → 验证器 r26 规则 → 跑 validate。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(
    "/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/"
    "audits/20260918-i32-adoption-dryrun"
)
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FROZEN = BASE / "freezes"
VALIDATOR = FROZEN / "validate_i0c_freeze.py"
MANIFEST = FROZEN / "freeze-manifest.json"
R26 = FROZEN / "i0c-r26.json"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
AUDIT = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-adoption-dryrun"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def patch_docs() -> list[str]:
    tasks = TASKS.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    changed: list[str] = []

    row_old = (
        "| I3-2 补料 | [证据目标候选 v6；r25 审批边界 B1—B5 修复（来源、原文映射、身份、投影）；"
        "no_decisions，未冻结正式金标，待复核与 U 裁决 40+24+6+1](claims-market-closed-loop-plan.md"
        "#i3-2-evidence-candidates) |"
    )
    row_new = (
        "| I3-2 补料 | [证据目标候选 v7 + **采纳稿落正式金标**（source-gold 36 槽位 = 冻结 23 条逐字节保留 + "
        "采纳 13 槽/49 条；负例近似命中 7 条隔离成库）；目标 54→82（必需 44／补充 20／锚点 18）；"
        "`blocked` 2→1（`macro-004` 人工裁定覆盖）；裁决件 40+24+6+1 已落，门 **ready=true**"
        "（0 阻断／20 条人工同义 warning），批准投影 79 必需 + 20 补充；验证 30/30 自洽 + 探针 16/16；"
        "i0c-r26](claims-market-closed-loop-plan.md#i3-2-evidence-candidates) |"
    )
    assert row_old in tasks, "tasks 表格行未找到"
    tasks = tasks.replace(row_old, row_new, 1)
    changed.append("tasks:表格行")

    anchor = "**I3-2 补料候选已按复验报告 B1—B5 修复（2026-09-18，A 侧，规则 `evidence-mapping-6`；见总台账"
    assert anchor in tasks, "tasks 段落未找到"
    new_block = (
        "**I3-2 采纳稿已落正式路径并冻结（2026-09-18，A 侧，规则仍 `evidence-mapping-6`；i0c-r26；见总台账\n"
        "[I3-2 补料](claims-market-closed-loop-plan.md#i3-2-evidence-candidates)）**：U 全文审核 AI 辅助补证"
        "与裁决建议后**全部采纳**（署名 `xyl` + `ai_assisted: true`，AI 复核者非人类签名）；新金标版本 = "
        "23 条冻结槽位**逐字节保留** + 采纳 13 槽位/49 条（逐条对账页内切片：页号 + quote 逐字 + quote_sha256），"
        "负例的 7 条近似命中外移为\n"
        f"[负例库](../../{BASE_REL}/i3-2/source-gold-nearmiss-library.jsonl)（不入映射池）；重映射后 30 题 → "
        "目标 **82** 条（必需 44／补充 20／待批准锚点 18）、`machine_ready` 2／`pending_human` 21／`blocked` 1／"
        "负例 6；裁决件\n"
        f"[40 要件 + 24 整题 + 6 负例 + 1 状态澄清](../../{BASE_REL}/i3-2/evidence-targets-decisions.json) 落盘后，\n"
        f"[门](../../{BASE_REL}/i3-2/approval-report.json) **ready=true（0 阻断）**、\n"
        f"[批准投影](../../{BASE_REL}/i3-2/evidence-targets-approved.json) 30 题 = 必需 **79** + 补充 20 条、\n"
        f"[验证](../../{BASE_REL}/i3-2/evidence-targets-verification.json) 自洽 30/30 + 探针 16/16。\n"
        "四项口径：①AI 核验锚点逐项确认同义（门记 20 条 warning，机器不宣称语义等价）；②无内容词元的纯日期 "
        "span 不作承载映射；③chosen 收窄到最小覆盖集（53→35，移出的 18 条记 `supporting_anchors`，"
        "不计入 EvidencePass）；④`macro-004` 的 `blocked`（q2 机器检索未登记承载项）由人工裁定覆盖，"
        "机器状态原样保留供审计。**仍未宣告 I3-2 完成**：I3-2 其余冻结项、I3-1（E2E）与 I3-5 真实答案语义"
        "验收未做；强制零模型、未写生产库、未读候选业务结果。\n\n"
        "**（本节以下为 r25 历史：候选 54 条与审批门 `no_decisions`）**：\n"
    )
    tasks = tasks.replace(anchor, new_block + anchor, 1)
    changed.append("tasks:当前状态段")

    old_cell = "审批门 no_decisions 待 40+24+6+1 项人工裁决）；M6—M8 未放行**"
    new_cell = (
        "**I3-2 采纳稿已落正式路径并经门放行（i0c-r26：金标 36 槽位、目标 82 条、裁决件 40+24+6+1、"
        "门 ready=true／0 阻断／20 条人工同义 warning、批准投影 79 必需 + 20 补充、验证 30/30 自洽 + 探针 16/16）**）；"
        "M6—M8 未放行**"
    )
    assert old_cell in plan, "plan 表格状态未找到"
    plan = plan.replace(old_cell, new_cell, 1)
    changed.append("plan:表格状态")

    old_state = (
        "**当前状态（r25 优先于本节历史 r24 数据）**：I3-2 补料候选 v6 + 复验 B1—B5 修复交付；"
        "**未冻结金标、未宣告 I3-2 完成**。"
    )
    new_state = (
        "**当前状态（r26 优先于本节历史 r25/r24 数据）**：I3-2 采纳稿落正式路径：新金标 36 槽位"
        "（冻结 23 条逐字节保留 + 采纳 13 槽/49 条，负例近似命中 7 条隔离成库）、候选 v7（82 条目标："
        "必需 44／补充 20／锚点 18）、裁决件 40+24+6+1（署名 `xyl` + `ai_assisted`）、"
        "**门 ready=true（0 阻断／20 条人工同义 warning）**、批准投影 79 必需 + 20 补充、"
        "验证 30/30 自洽 + 探针 16/16。**未宣告 I3-2 完成**：其余冻结项与 I3-1/I3-5 未做。\n\n"
        "**历史 r25 状态**：I3-2 补料候选 v6 + 复验 B1—B5 修复交付；未冻结金标、未宣告 I3-2 完成。"
    )
    assert old_state in plan, "plan 当前状态未找到"
    plan = plan.replace(old_state, new_state, 1)
    changed.append("plan:当前状态段")

    TASKS.write_text(tasks, encoding="utf-8")
    PLAN.write_text(plan, encoding="utf-8")
    return changed


R26_BLOCK = '''
if "i0c-r26" in by_id:
    i0c26 = load_json(BASE / by_id["i0c-r26"].get("file", ""))
    parent = i0c26.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r25"]["file"]
    check(parent.get("snapshot_id") == "i0c-r25", "r26 parent must be r25")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r26 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r26 parent bytes mismatch")
    binding26 = i0c26.get("binding", {})
    corrections = i0c26.get("corrections", {})
    for finding in ("I3-2_adoption", "human_signature", "required_supplementary_scope",
                    "machine_status_override", "verifier_probe_update", "I3-5"):
        check(finding in corrections, f"r26 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260918-i32-adoption-dryrun"
    allowed = {
        "i3_2_tooling": {f"{base}/{name}.py" for name in (
            "i3s2_evidence_targets", "i3s2_apply_decisions", "i3s2_verify_candidates",
            "i3s2_textutil")},
        "i3_2_source_gold": {f"{base}/{name}" for name in (
            "source-gold-frozen.jsonl", "query-gold-frozen.jsonl")},
        "i3_2_assets": {f"{base}/i3-2/{name}" for name in (
            "evidence-targets-candidates.json", "evidence-targets-adjudication.md",
            "evidence-targets-review.md", "evidence-targets-verification.json",
            "approval-report.json", "evidence-targets-decisions.json",
            "evidence-targets-approved.json", "source-gold-nearmiss-library.jsonl")},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding26) == set(allowed) | {"i3_2_regressions", "i3_2_archive"},
          "r26 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding26.get(group, {})) == expected, f"r26 unexpected {group} scope")
    for name in ("evidence-targets-candidates-v6.json", "evidence-targets-review-v6.md",
                 "evidence-targets-adjudication-v3.md", "evidence-targets-verification-v4.json",
                 "approval-report-v2.json"):
        check(f"{base}/i3-2/{name}" in binding26.get("i3_2_archive", {}),
              f"r26 missing archive {name}")
    gold_archive = f"{audit}/before-r26/{base}/source-gold-frozen.jsonl"
    check(gold_archive in binding26.get("i3_2_archive", {}),
          "r26 missing r25 source-gold byte archive")
    for rel in binding26.get("i3_2_regressions", {}):
        check(str(Path(rel).parent) == audit and ".." not in Path(rel).parts,
              f"r26 regression binding out of scope {rel}")
    for name in ("report.md", "run_adoption_dryrun.py", "promote_i3s2.py", "promote-log.json",
                 "dryrun-result.json", "decisions-final-dryrun.json", "gate-final-dryrun.json",
                 "release-manifest.json", "verification-v7-dryrun.json"):
        check(f"{audit}/{name}" in binding26.get("i3_2_regressions", {}),
              f"r26 missing regression {name}")
    for group, items in binding26.items():
        for rel in items:
            check(not rel.startswith(("plugins/", "tests/", "guards/")),
                  f"r26 越界绑定 {rel}（本轮不改实现/测试/守卫）")
    check(
        binding26.get("i3_2_source_gold", {}).get(f"{base}/source-gold-frozen.jsonl")
        == digest(ROOT / f"{base}/source-gold-frozen.jsonl"),
        "r26 source-gold binding mismatch",
    )
    merge_binding(i0c_current_binding, binding26)

'''


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r26" in by_id:' in text:
        return {"already_patched": True}
    check_line = 'check("i0c-r24" in by_id, "索引缺少 i0c-r24 条目")'
    assert check_line in text
    text = text.replace(
        check_line,
        check_line + '\ncheck("i0c-r25" in by_id, "索引缺少 i0c-r25 条目")\n'
        'check("i0c-r26" in by_id, "索引缺少 i0c-r26 条目")',
        1,
    )
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r25 显式重绑的路径改由合并后的"
    assert anchor in text
    text = text.replace(
        anchor,
        R26_BLOCK + "# 最新修订绑定优先（supersession）：i0c-r2..r26 显式重绑的路径改由合并后的",
        1,
    )
    tail = '+ ("r25 B1-B5 approval remediation verified, candidates only" if "i0c-r25" in by_id else ""))'
    assert tail in text
    text = text.replace(
        tail,
        '+ ("r26 I3-2 adoption verified (new source-gold 36 slots, 82 targets, filed decisions, '
        'gate ready=true, approved projection 79+20)" if "i0c-r26" in by_id else ""))',
        1,
    )
    doc_anchor = "13. i0c-r24 = I3-2 补料**二轮复核 A1—A5 整改**"
    assert doc_anchor in text
    text = text.replace(
        "\\n    ``plugins/``／``tests/``／守卫绑定。\n\"\"\"",
        "\\n    ``plugins/``／``tests/``／守卫绑定。\\n"
        "14. i0c-r26 = **I3-2 采纳稿落正式路径**（新金标 36 槽位 + 候选 v7 + 裁决件/批准投影/门/验证；\\n"
        "    规则仍 evidence-mapping-6）：绑 ``i3_2_tooling``／``i3_2_source_gold``（金标首次直接入链）／\\n"
        "    ``i3_2_assets``／``i3_2_archive``（r25 被覆盖字节 + 替换前金标）／``i3_2_regressions``（采纳审计目录）／\\n"
        "    台账／验证器；同样**不得**出现 ``plugins/``／``tests/``／守卫绑定。\\n\"\"\"",
        1,
    )
    VALIDATOR.write_text(text, encoding="utf-8")
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


def build_r26(regressions: dict[str, str]) -> dict:
    def entry(path: Path) -> str:
        return digest(path)

    binding = {
        "i3_2_tooling": {
            f"{BASE_REL}/{name}.py": entry(BASE / f"{name}.py")
            for name in ("i3s2_evidence_targets", "i3s2_apply_decisions", "i3s2_verify_candidates",
                         "i3s2_textutil")
        },
        "i3_2_source_gold": {
            f"{BASE_REL}/{name}": entry(BASE / name)
            for name in ("source-gold-frozen.jsonl", "query-gold-frozen.jsonl")
        },
        "i3_2_assets": {
            f"{BASE_REL}/i3-2/{name}": entry(BASE / "i3-2" / name)
            for name in (
                "evidence-targets-candidates.json", "evidence-targets-adjudication.md",
                "evidence-targets-review.md", "evidence-targets-verification.json",
                "approval-report.json", "evidence-targets-decisions.json",
                "evidence-targets-approved.json", "source-gold-nearmiss-library.jsonl",
            )
        },
        "i3_2_archive": {
            **{
                f"{BASE_REL}/i3-2/{name}": entry(BASE / "i3-2" / name)
                for name in (
                    "evidence-targets-candidates-v6.json", "evidence-targets-review-v6.md",
                    "evidence-targets-adjudication-v3.md",
                    "evidence-targets-verification-v4.json", "approval-report-v2.json",
                )
            },
            f"{AUDIT}/before-r26/{BASE_REL}/source-gold-frozen.jsonl": entry(
                HERE / "before-r26" / BASE_REL / "source-gold-frozen.jsonl"
            ),
        },
        "i3_2_regressions": regressions,
        "docs": {
            rel(TASKS): entry(TASKS),
            rel(PLAN): entry(PLAN),
        },
        "freeze_validator": {rel(VALIDATOR): entry(VALIDATOR)},
    }
    r25 = json.loads((FROZEN / "i0c-r25.json").read_text(encoding="utf-8"))
    del r25
    return {
        "snapshot_id": "i0c-r26",
        "revision": "r26",
        "phase": "i0c",
        "task": (
            "I3-2 adoption of the AI-assisted supplement package: new source-gold (36 slots, frozen 23 "
            "byte-preserved), regenerated candidates (82 targets), filed human decisions (xyl, ai_assisted), "
            "gate ready=true with 20 manual-synonymy warnings, approved projection 79 required + 20 "
            "supplementary, verification 30/30 self-consistency + 16/16 probes"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r25",
            "path": rel(FROZEN / "i0c-r25.json"),
            "sha256": digest(FROZEN / "i0c-r25.json"),
        },
        "binding": binding,
        "corrections": {
            "I3-2_adoption": (
                "U 全文审核后全部采纳 AI 辅助补证与裁决建议：金标 23 条冻结槽位逐字节保留 + 采纳 "
                "13 槽位/49 条支持证据，负例近似命中 7 条隔离成 i3-2/source-gold-nearmiss-library.jsonl"
            ),
            "human_signature": (
                "署名人为具名审核人 xyl（已全文审核），同时记录 ai_assisted=true 与 ai_reviewer_label"
                "（AI 复核者不是人类签名）；不冒签、不改写历史审核记录"
            ),
            "required_supplementary_scope": (
                "chosen 收窄到最小覆盖集（53→35），移出的 18 条锚点记 supporting_anchors 且不计入 "
                "EvidencePass；批准投影 = 必需 79 + 补充 20（30 题）"
            ),
            "machine_status_override": (
                "macro-004 的 blocked（q2『本文聚焦前四者』机器检索未登记承载项）由人工裁定以 "
                "macro-ai-supplement-2026-09-06_cc03f55b-p1#1 为承载；机器状态原样保留在候选里"
            ),
            "verifier_probe_update": (
                "P5-supplementary-not-required 期望值随补证采纳更新（company-005 补充目标新增 p3 槽位"
                "两条），属版本化改动，已在探针描述里写明理由"
            ),
            "I3-5": (
                "I3-5 真实生成答案语义验收仍未执行：本轮只完成零模型的证据目标批准链"
                "（门 ready=true），不代表答案语义通过"
            ),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "source-gold 变更（23 条冻结槽位逐字节保留 + 13 个采纳槽位）；query-gold、守卫、评分器、"
            "公共模块、tests、数据库与模型均未改（零模型、零数据库写入）。",
            "批准件的 20 条 warning 全为『人工同义映射待审计（非机器语义证明）』：机器只核 span 出处，"
            "语义等价由具名人工承担。",
            "I3-2 其余冻结项（阈值/关键题/负例/旧基线映射）、I3-1（E2E）与 I3-5 未做；未宣告 I3-2 完成。",
        ],
    }


def main() -> int:
    changed = patch_docs()
    patched = patch_validator()
    regressions = {
        f"{AUDIT}/{path.name}": digest(path)
        for path in sorted(HERE.iterdir())
        if path.is_file()
        and path.name
        in {
            "report.md", "run_adoption_dryrun.py", "promote_i3s2.py", "promote-log.json",
            "dryrun-result.json", "decisions-final-dryrun.json", "gate-final-dryrun.json",
            "release-manifest.json", "verification-v7-dryrun.json", "blocker-help.json",
            "protected-artifacts-check.json", "decisions-dryrun.json", "gate-dryrun.json",
            "decisions-proposed-synonymy.json", "gate-proposed-synonymy.json",
            "gate-upperbound.json", "source-gold-v4-candidate.jsonl",
            "source-gold-nearmiss-library.jsonl", "candidates-v7-dryrun.json",
            "review-v7-dryrun.md", "adjudication-v7-dryrun.md",
        }
    }
    r26 = build_r26(regressions)
    R26.write_text(json.dumps(r26, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not any(entry.get("snapshot_id") == "i0c-r26" for entry in manifest["snapshots"]):
        manifest["snapshots"].append(
            {
                "snapshot_id": "i0c-r26",
                "file": "i0c-r26.json",
                "sha256": digest(R26),
                "parent_snapshot_id": "i0c-r25",
                "created_at": r26["created_at"],
            }
        )
        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    proc = subprocess.run(
        [sys.executable, str(VALIDATOR)], capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    print(json.dumps({
        "docs_changed": changed,
        "validator": patched,
        "r26_sha256": digest(R26),
        "manifest_entries": len(json.loads(MANIFEST.read_text(encoding="utf-8"))["snapshots"]),
        "validate_exit": proc.returncode,
        "validate_out": (proc.stdout or "").strip().splitlines()[-2:],
        "validate_err": (proc.stderr or "").strip().splitlines()[-3:],
    }, ensure_ascii=False, indent=2))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
