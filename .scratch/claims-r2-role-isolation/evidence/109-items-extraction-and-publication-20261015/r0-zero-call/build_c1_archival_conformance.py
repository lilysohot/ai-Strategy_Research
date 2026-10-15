"""归档前合规分析：把 C1 的 15 条判成 no_candidate，是否符合发布标准与执行链路。

只读、零模型调用。逐条规则追到原文（件 + 行/键 + 哈希），给出 compliant / conflict / pending，
并显式列出需要 U 裁的口径冲突。不产出任何处置结论：本件回答的是"这么做合不合规"。

Usage:
    python build_c1_archival_conformance.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import write_once  # noqa: E402

CREATED_ON = "2026-10-15"

PROPOSAL = HERE / "items-extraction-publication-proposal.json"
PREREG_V2 = HERE / "items-reextraction-preregistration-v2.json"
GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
CONTRACT_V43 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
TERMINAL_72 = (
    ROOT
    / "evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/terminal-decision.json"
)
CORRECTIONS_72 = (
    ROOT / "evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/corrections.md"
)
REG_92 = (
    ROOT
    / "evidence/92-claims-scope-registration-20261014/r0-zero-call/claims-scope-registration.json"
)
R3_SUMMARY = HERE / "items-reextract-plan-freeze-r3/execution-summary.json"
GAP_ANALYSIS = HERE / "p4-remaining-gap-analysis.json"
REVIEW_LISTING = HERE / "p4-c1-review-listing.json"
P5_RECORD = HERE / "p5-release-record.json"
C1_RATIFICATION = HERE / "p5-c1-reading-ratification.json"
U_RULINGS = HERE / "p5-u-rulings-20261015.json"
C1_FINAL = HERE / "p4-c1-disposition-final.json"
RELEASE_SCRIPT = HERE / "build_p5_release_and_c1_ledger.py"
SCORER = REPO_ROOT / "plugins/corpus/structured_scoring.py"

OUT = HERE / "p4-c1-archival-conformance.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


CITED_FRAGMENTS = (
    "补抽产出相同片段，会被同一裁定口径再判 correct_extra；缺口在裁定口径而非抽取",
    "14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖）",
)


def verify_citations() -> None:
    """本件的每条引用都必须在被引件里逐字找到；找不到即拒绝出件（防引用漂移）。"""
    corrections = CORRECTIONS_72.read_text(encoding="utf-8")
    for fragment in CITED_FRAGMENTS:
        if fragment not in corrections:
            raise SystemExit(f"引用在 72 号 corrections.md 中找不到：{fragment}")
    proposal = load(PROPOSAL)
    p4 = next(step for step in proposal["plan"] if step["step"] == "P4")
    if "29 条" not in p4["what"] or "no_candidate" not in p4["what"]:
        raise SystemExit("立项件 P4 步不再含 29 条处置条款，本件前提失效")


def build() -> dict[str, Any]:
    verify_citations()
    prereg = load(PREREG_V2)
    r3 = load(R3_SUMMARY)
    gap = load(GAP_ANALYSIS)
    listing = load(REVIEW_LISTING)
    p5 = load(P5_RECORD)

    authored = listing["basis"]["candidate_set"]["sha256"]
    at_issue = [row for row in listing["rows"] if row["machine_disposition_v1"] == "no_candidate"]

    publication_rules = [
        {
            "rule": "发布标准（结构完备性）与门阈值/金标解耦；按 U 裁定走『显式缺口』路线",
            "source": "evidence/72-…/r0-zero-call/build_terminal_record.py:267；terminal-decision.json",
            "requirement": "内容可以未被覆盖，但必须在发布件里明写为缺口",
            "verdict": "compliant",
            "why": "把 15 条判 no_candidate 并列入发布件缺口清单，正是该路线的规定动作",
        },
        {
            "rule": "P6 验收：生产 store material_items coverage missing → complete",
            "source": "items-extraction-publication-proposal.json::acceptance_criteria[4]",
            "requirement": "coverage 补全针对**已接受记录**，不针对 C1 内容",
            "verdict": "compliant",
            "why": "C1 内容不是 items 候选、不进 store 记录，归档与否都不改 coverage 完整性判定",
        },
        {
            "rule": "移出 claims 判据的候选必须在 items/relations 侧登记为待覆盖，不得就地丢弃",
            "source": "evidence/92-…/claims-scope-registration.json::basis.rule",
            "requirement": "必须留下登记；允许的状态是『待覆盖』",
            "verdict": "compliant",
            "why": "记 no_candidate 于 checklist 属『登记』，非『丢弃』；预注册 v2 明文把 no_candidate 写成允许结论",
        },
        {
            "rule": "门 v3 哨兵 11/11、召回/精度轴",
            "source": "gate-v3.json（已签 340b312d…）",
            "requirement": "只对 items 金标计分",
            "verdict": "compliant",
            "why": "C1 的 29 条不是金标、不在 199 行池内 ⇒ 归档不触碰任何判定轴读数",
        },
        {
            "rule": "既有 claims 发布件字节不动",
            "source": "items-extraction-publication-proposal.json::acceptance_criteria[4]",
            "requirement": "P6 不得重写 106/108 号产物",
            "verdict": "compliant",
            "why": "归档只新增 items 侧记录；92 号 claims 侧登记件亦不改（只被引用）",
        },
    ]

    chain_rules = [
        {
            "rule": "P4 含 92 号 29 条处置：有对应候选入裁定、无候选记 no_candidate",
            "source": "items-extraction-publication-proposal.json::plan[P4]",
            "requirement": "15 条归档是 P4 的**规定动作**，不是额外工序",
            "verdict": "compliant",
            "why": "链路序位：P4（含 29 条）→ P5（出分 + U 签认放行）→ P6（发布）⇒ 归档必须在 P5 之前闭合",
        },
        {
            "rule": "建议仅加速人工裁定、不替代裁定；机械预填不得污染人工校准记录（65 号教训）",
            "source": "items-reextraction-preregistration-v2.json::stage1_suggester.note；acceptance_criteria[2]",
            "requirement": "裁决人须 U 具名；机械结论只能作建议",
            "verdict": "compliant_with_condition",
            "why": (
                "工作表 c1_pending_coverage 的 disposition 至今 29/29 为空，机械结论只落在旁路件"
                "（p4-c1-disposition.json / p4-c1-review-listing.json）⇒ 人工校准记录未被污染；"
                "但若改由 assistant 按『语义相同』直接判，则须另记录为『U 授权机械裁定 + 抽样复核』，"
                "否则触本条的机械预填禁令"
            ),
        },
        {
            "rule": "Stage-2 全量逐条 U 具名裁定；批次清单按批留档",
            "source": "items-extraction-publication-proposal.json::acceptance_criteria[2]",
            "requirement": "15 条须 U 具名 + 清单留档",
            "verdict": "position_approved_rulings_pending",
            "why": (
                "裁决人已定：U 亲判（R1 明确不授权机械裁定）；清单已备"
                "（p4-c1-review-listing.json 7370383b…，29 条两侧原文）。"
                "剩余动作是 U 对 15 条逐条给方向，rulings 栏待填"
            ),
        },
        {
            "rule": "threshold_relaxation_after_execution_allowed = false",
            "source": "items-reextraction-preregistration-v2.json::scope_constraints",
            "requirement": "不得在执行后放宽已冻口径",
            "verdict": "compliant",
            "why": (
                "本条管的是抽取/裁定的执行约束；0.55 字面相似度阈值从未进入任何预注册件，"
                "它不是『已签阈值』⇒ 去掉它不属于放宽。本件据此不改动任何已冻件，只另立记录"
            ),
        },
        {
            "rule": "new_gold_allowed = false；holdout_accessed = false",
            "source": "items-reextraction-preregistration-v2.json::scope_constraints",
            "requirement": "归档不得引入新金标或触碰 holdout",
            "verdict": "compliant",
            "why": "归档只读两侧原文（C1 文本 + 池内候选文本），不引用、不新增金标",
        },
        {
            "rule": "判定只用 reading_axes.primary；条数下限不另立独立判定轴",
            "source": "items-reextraction-preregistration-v2.json::reading_axes.note（claims 95 号 v2 教训）",
            "requirement": "门读数按 5 轴（overall recall / per-source recall / precision / unresolved / sentinels）读；accepted 条数下限属 diagnostic",
            "verdict": "resolved_by_two_independent_routes",
            "why": (
                "评分器照抛出 accepted_records_per_source:18<20（plugins/corpus/structured_scoring.py:1218），"
                "与预注册 v2『条数下限不另立轴』看似冲突；实测两条独立路径都指向同一结论："
                "① 判定轴路径：按 reading_axes 五轴读，唯一未达标为哨兵 NT-I43；"
                "② 复算路径：按合同自身的派生规则 floor(0.85×目标规模) 复算（该规则能把合同 total 下限 40 逐字复现："
                "floor(0.85×48)=40），合同的 per_source=20 恰等于 floor(0.85×48/2)=20 ⇒ 它是『两源均分』假设的产物；"
                "按实际分源目标 22/26 复算应为 18/22，而 md 实测 18 恰在线上。"
                "两路不改合同任何字节，只登记。详见 p5-release-record.json::reading_layers"
            ),
        },
    ]

    criteria = {
        "primary_axes": prereg["reading_axes"]["primary"],
        "diagnostic_only": prereg["reading_axes"]["diagnostic_only"],
        "outcome_if_reading_axes_govern": {
            "target_recall_overall": "41/48 = 0.8542 ≥ 0.85 PASS",
            "target_recall_per_source": "md 18/22 = 0.8182、docx 23/26 = 0.8846 ≥ 0.80 PASS",
            "candidate_precision": "191/199 = 0.9598 ≥ 0.80 PASS",
            "unresolved_candidates": "0 = 0 PASS",
            "sentinel_assertions": "10/11 FAIL（缺 NT-I43）",
            "sole_failing_axis": "sentinel_assertions",
        },
        "scorer_verbatim_blockers": p5["gate_reading"]["rate_blockers"],
        "blocker_decomposition": [
            {
                "blocker": "contract_high_risk_assertion_unmatched:NT-I43",
                "class": "判定轴内",
                "note": "sentinel_assertions 是 reading_axes.primary 之一 ⇒ 唯一轴内未达标项",
            },
            {
                "blocker": "critical_gold_missing:NT-I43",
                "class": "同一事实的另一读数视图",
                "note": "NT-I43 同时 critical=true，与上一条同源同一条金标，不构成独立缺口",
            },
            {
                "blocker": "contract_below_threshold:accepted_records_per_source:sha256:f8fa…:18<20",
                "class": "合同 blocker 但非判定轴",
                "note": (
                    "预注册 v2 明写条数下限不另立独立判定轴；另按合同自身的派生规则复算："
                    "floor(0.85×48)=40 与合同 total 下限逐字相符（自洽性证明该规则即合同自己的派生规则），"
                    "而 per_source=20=floor(0.85×48/2) ⇒ 来自『两源均分』假设；"
                    "按实际分源目标 22/26 复算应为 18/22，md 实测 18 恰在线上。"
                    "结论：该 blocker 是均分假设的产物，非独立质量缺口"
                ),
            },
        ],
    }

    no_more_extraction = {
        "question": "是否要再花额度定向补抽这些缺口？",
        "answer": "不补",
        "evidence": [
            {
                "source": "evidence/72-…/corrections.md:42（校正 #4）",
                "statement": "『补抽产出相同片段，会被同一裁定口径再判 correct_extra；缺口在裁定口径而非抽取』",
            },
            {
                "source": "evidence/72-…/corrections.md:40（校正 #2）",
                "statement": "『14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖）；0 条落在 evidence/32 记录的 9 个未产出槽』",
            },
            {
                "source": "items-reextract-plan-freeze-r3/execution-summary.json",
                "statement": (
                    f"round-3 全量重抽已执行：new_model_calls={r3['new_model_calls']}，"
                    f"total_tokens={r3['tokens_used']['total_tokens']}，"
                    "attempt_status md 10/10、docx 14/14 succeeded，automatic_retries=0；"
                    "仍缺 7 条金标 ⇒ 非额度问题"
                ),
            },
            {
                "source": "p4-remaining-gap-analysis.json",
                "statement": (
                    "7 条未覆盖金标在 158 行未匹配候选中的最高字面相似度 "
                    f"{min(g['best_similarity'] for g in gap['gaps'])}–"
                    f"{max(g['best_similarity'] for g in gap['gaps'])} ⇒ 池内无承载候选，改判也回收不了"
                ),
            },
        ],
    }

    return {
        "schema_version": "items-c1-archival-conformance-1",
        "id": "109-p4-c1-archival-conformance",
        "created_on": CREATED_ON,
        "model_calls": 0,
        "production_pg_writes": 0,
        "status": "pre_analysis_for_human_ruling",
        "question": "把这 15 条（现被机械判为 no_candidate 的条目）归档为缺口，是否符合发布标准与执行链路？",
        "short_answer": {
            "publication": "符合——72 号『显式缺口』路线允许内容未被覆盖，只要求明写；C1 不进任何判定轴读数",
            "execution_chain": "符合，且是 P4 的规定动作；但必须在 P5（放行签认）之前由 U 具名闭合",
            "deviation_from_goal": (
                "无。表面冲突『条数下限是否算判定轴』已由两条独立路径收敛（判定轴读法 + 合同自身派生规则复算），"
                "都指向『唯一实质未达标 = 哨兵 NT-I43』；不需二选一，也不改任何已签件。"
                "该读法已由 U 认可（p5-c1-reading-ratification.json）"
            ),
        },
        "archive_target_definition": {
            "rows_total": 29,
            "rows_mechanically_no_candidate": len(at_issue),
            "rows_covered": 29 - len(at_issue),
            "rows_finally_no_candidate": load(C1_FINAL)["summary"]["no_candidate"],
            "rows_finally_covered": load(C1_FINAL)["summary"]["covered_by_candidate"],
            "final_counts_source": str(C1_FINAL.relative_to(ROOT)),
            "what_archive_means": (
                "在工作表 checklist 的 disposition 填 no_candidate ⇒ 该内容被登记为『跨角色均无覆盖』，"
                "并进入发布件的显式缺口清单。不是丢弃：项目仍留在 92 号登记件与 checklist 中"
            ),
            "what_archive_does_not_mean": [
                "不是删除该内容",
                "不是改判任何候选行",
                "不是改门读数或放宽阈值",
                "不是宣称 items 覆盖完整",
            ],
        },
        "inputs": {
            "proposal": {"path": str(PROPOSAL.relative_to(ROOT)), "sha256": sha256(PROPOSAL)},
            "prereg_v2": {"path": str(PREREG_V2.relative_to(ROOT)), "sha256": sha256(PREREG_V2)},
            "gate_v3": {"path": str(GATE_V3.relative_to(ROOT)), "sha256": sha256(GATE_V3)},
            "contract_v43": {
                "path": str(CONTRACT_V43.relative_to(ROOT)),
                "sha256": sha256(CONTRACT_V43),
            },
            "terminal_72": {
                "path": str(TERMINAL_72.relative_to(ROOT)),
                "sha256": sha256(TERMINAL_72),
            },
            "corrections_72": {
                "path": str(CORRECTIONS_72.relative_to(ROOT)),
                "sha256": sha256(CORRECTIONS_72),
            },
            "registration_92": {"path": str(REG_92.relative_to(ROOT)), "sha256": sha256(REG_92)},
            "round3_execution_summary": {
                "path": str(R3_SUMMARY.relative_to(ROOT)),
                "sha256": sha256(R3_SUMMARY),
            },
            "gap_analysis": {
                "path": str(GAP_ANALYSIS.relative_to(ROOT)),
                "sha256": sha256(GAP_ANALYSIS),
            },
            "review_listing": {
                "path": str(REVIEW_LISTING.relative_to(ROOT)),
                "sha256": sha256(REVIEW_LISTING),
            },
            "p5_release_record": {
                "path": str(P5_RECORD.relative_to(ROOT)),
                "sha256": sha256(P5_RECORD),
            },
            "c1_reading_ratification": {
                "path": str(C1_RATIFICATION.relative_to(ROOT)),
                "sha256": sha256(C1_RATIFICATION),
            },
            "u_rulings": {
                "path": str(U_RULINGS.relative_to(ROOT)),
                "sha256": sha256(U_RULINGS),
            },
            "c1_disposition_final": {
                "path": str(C1_FINAL.relative_to(ROOT)),
                "sha256": sha256(C1_FINAL),
            },
            "scorer": {"path": str(SCORER.relative_to(REPO_ROOT)), "sha256": sha256(SCORER)},
            "candidate_set_u_authored": {
                "path": listing["basis"]["candidate_set"]["path"],
                "sha256": authored,
            },
        },
        "publication_rules": publication_rules,
        "execution_chain_rules": chain_rules,
        "criteria_reading": criteria,
        "no_further_extraction": no_more_extraction,
        "conflicts_requiring_u": [
            {
                "id": "C-1",
                "title": "条数下限（accepted_records_per_source）是否算判定轴",
                "status": "ratified_by_u——读法已获认可，见 p5-c1-reading-ratification.json",
                "sides": [
                    "评分器/合同 v4.3：当作合同 blocker（md 18<20 ⇒ rate_gate_passed=false）",
                    "预注册 v2 reading_axes：判定只用 5 轴，条数下限不另立轴 ⇒ 只算诊断读数",
                ],
                "reconciliation": {
                    "route_1_judgement_axes": "按 reading_axes 五轴读 ⇒ 唯一未达标 = 哨兵 NT-I43",
                    "route_2_contract_self_derivation": (
                        "按合同自身的派生规则 floor(0.85×目标规模) 复算：total floor(0.85×48)=40 与合同逐字相符"
                        "（自洽性证明）；per_source 20 = floor(0.85×48/2) ⇒ 来自两源均分假设；"
                        "按实际目标 22/26 复算为 18/22，md 实测 18 恰在线上"
                    ),
                    "convergence": "两路都指向『唯一实质未达标 = 哨兵 NT-I43』",
                    "cost": "零——不改合同字节、不改评分器、不改阈值，只登记",
                },
                "consequence": "P5 判档措辞写『轴内 1 项未达标（哨兵）』，并把 rate_gate_passed=false 作为合同层读数并列保留",
                "needs": "已闭合",
                "ratification": {
                    "path": str(C1_RATIFICATION.relative_to(ROOT)),
                    "sha256": sha256(C1_RATIFICATION),
                    "status": load(C1_RATIFICATION)["status"],
                    "u_statement": load(C1_RATIFICATION)["u_statement"]["verbatim"],
                },
            },
            {
                "id": "C-2",
                "title": "15 条的裁决人是谁",
                "sides": [
                    "U 逐条点『是/不是』⇒ 完全符合 stage1_suggester 禁令",
                    "U 授权 assistant 按『语义相同』判 + 抽样复核 ⇒ 须另记『授权机械裁定』，否则触机械预填禁令",
                ],
                "consequence": "决定发布件缺口清单的条目数，以及人工校准记录是否被机械结论污染",
                "status": "closed——U 不授权机械裁定并已逐条给方向，处置已定稿",
                "needs": "已闭合",
                "ruling": {
                    "path": str(U_RULINGS.relative_to(ROOT)),
                    "sha256": sha256(U_RULINGS),
                    "u_statement": next(
                        item["verbatim"]
                        for item in load(U_RULINGS)["rulings"]
                        if item["id"] == "R1"
                    ),
                },
                "outcome": {
                    "path": str(C1_FINAL.relative_to(ROOT)),
                    "sha256": sha256(C1_FINAL),
                    "u_ruling_verbatim": load(C1_FINAL)["u_ruling_verbatim"],
                    "summary": load(C1_FINAL)["summary"],
                    "note": "3 条由 no_candidate 翻为 covered（#8/#18/#25）；#2 维持 no_candidate（U 判『有相似的词，但含义主体不同』）",
                },
            },
        ],
        "verdict": {
            "publication_conformant": True,
            "execution_chain_conformant": True,
            "deviates_from_publication_goal": False,
            "preconditions": [
                "15 条 U 亲判已闭合（C-2），并已落回工作表 checklist（r3-c1ruled 修订版）",
                "发布件必须逐条列出缺口（不得只写总数）",
                "C-1 的口径已在 P5 判档措辞中明确（已获 U 认可，见 ratification 件）",
                "199 行署名出处已闭合（R2 确认亲笔）",
                "唯一剩余动作：U 具名签认 P5 放行 ⇒ 方可起 P6/P7",
            ],
        },
        "untouched": [
            f"工作表两版字节未动（disposition 仍 29/29 为空；U 源件 {authored[:12]}…）",
            "92 号登记件、预注册 v1/v2、门 v3、契约 v4.3、83–108 号产物均未动",
            "未写生产 PG、未发布、未补抽、未代签",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    payload = build()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.no_write:
        print(text)
        return 0
    write_once(OUT, text, reason="C1 归档前合规分析", allow_overwrite=args.force)
    print(f"wrote {OUT.name}")
    print(json.dumps(payload["short_answer"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
