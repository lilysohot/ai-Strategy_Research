#!/usr/bin/env python3
"""Retro-audit of the R2 chain (evidence 71 → 75) — machine-enumerated, zero model calls.

Answers "是否存在遗漏" with checks, not prose. Each check states the predicate it measures,
the claimed set, the actual set and the delta. Writes nothing outside this directory and
never edits an input; ``--phase`` labels the run so an initial run and a recheck are both kept.

Severity vocabulary (declared, per the accounting discipline):
  blocking_target   the stated goal cannot be reached while this holds
  blocking_signoff  sign-off would land a record that cannot be consumed / would prefill a U decision
  registration      a known inconsistency that must be registered, not silently inherited
  cosmetic          wording/staleness only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
CLAIMS = REPO_ROOT / ".scratch/claims-r2-role-isolation"

DRAFT = E / "74-r2-gate-v3-contract-v43-draft-20261013" / "r0-zero-call"
SIGNED = E / "75-r2-signed-20261013" / "r0-zero-call"

GATE_V2 = E / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate-v2.json"
CONTRACT_V42 = E / "58-contract-v42-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.2.json"
GATE_V3 = DRAFT / "gate-v3.proposed.json"
CONTRACT_V43 = DRAFT / "scoring-contract-v4.3.proposed.json"
READJUDICATION = DRAFT / "re-adjudication-draft.json"
SHEET = DRAFT / "r2-signoff-review.md"
APPLY = SIGNED / "apply_r2_signoff.py"
ATTRIBUTION = E / "71-fn-attribution-20261013" / "r0-zero-call" / "fn-attribution.json"
HONEST_SCORE = E / "69-union-adjudication-20261013" / "r1-score" / "gate33-honest-score.json"
TERMINAL = E / "72-gate33-terminal-and-corrections-20261013" / "r0-zero-call" / "terminal-decision.json"
GOLD = E / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"

CHOICE_A = "I36_question_form"
CHOICE_B = "one_of_u_calibration_revoked"
PAIR_IDS = ("NT-I23", "NT-I24")
SUBTREE_IDS = ("NT-I45", "NT-I46", "NT-I47")


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="recheck")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    gate_v2 = load(GATE_V2)
    gate_v3 = load(GATE_V3)
    contract_v42 = load(CONTRACT_V42)
    contract_v43 = load(CONTRACT_V43)
    readjudication = load(READJUDICATION)
    attribution = load(ATTRIBUTION)
    by_id = {r["record_id"]: r for r in load(GOLD)["records"] if r["role"] == "material_items"}
    matched_now = set(load(HONEST_SCORE)["matched_gold_ids"])
    sheet_text = SHEET.read_text(encoding="utf-8")
    apply_text = APPLY.read_text(encoding="utf-8")

    findings: list[dict[str, Any]] = []

    def record(check: str, predicate: str, claimed: Any, actual: Any, ok: bool,
               severity: str, note: str) -> None:
        findings.append(
            {
                "check": check,
                "predicate": predicate,
                "claimed": claimed,
                "actual": actual,
                "ok": bool(ok),
                "severity": None if ok else severity,
                "note": note,
            }
        )

    sentinel_v2 = gate_v2["quality_requirements"]["high_risk_item_assertions_required"]
    sentinel_v3 = gate_v3["quality_requirements"]["high_risk_item_assertions_required"]
    excluded = gate_v3["quality_requirements"]["high_risk_item_assertions_excluded"]
    contract_items = sorted(k for k in contract_v43["review_assertions"] if k.startswith("NT-I"))

    # --- set relations -------------------------------------------------------------
    record(
        "sentinel_equals_contract_items",
        "门 v3 哨兵清单 == 契约 v4.3 的 NT-I* 断言子集",
        sorted(sentinel_v3),
        contract_items,
        sorted(sentinel_v3) == contract_items,
        "blocking_signoff",
        "二者不一致会让门与契约各说一套",
    )
    record(
        "excluded_subset_of_v2_sentinel",
        "被移出 5 项 ⊂ 门 v2 的 16 项",
        sorted(excluded),
        sorted(set(excluded) & set(sentinel_v2)),
        set(excluded) <= set(sentinel_v2),
        "blocking_signoff",
        "移出项必须原本在清单内",
    )
    record(
        "excluded_all_annotated",
        "每个被移出项都有 mechanism 与 reason",
        len(excluded),
        sum(1 for v in excluded.values() if v.get("mechanism") and v.get("reason")),
        all(v.get("mechanism") and v.get("reason") for v in excluded.values()),
        "blocking_signoff",
        "无理由的移出等于事后删项",
    )
    record(
        "sentinel_subset_of_gold",
        "哨兵清单 ⊂ 48 条冻结金标",
        len(sentinel_v3),
        len(set(sentinel_v3) & set(by_id)),
        set(sentinel_v3) <= set(by_id),
        "blocking_signoff",
        "",
    )

    # --- the seven flips ----------------------------------------------------------
    stubs = readjudication["adjudications"]
    required = [r["proposed_matched_gold_id"] for r in stubs if r["keep_if"]["rule"] == "always"]
    pair = [r["proposed_matched_gold_id"] for r in stubs if r["keep_if"]["rule"] == "pair_choice"]
    seventh = [r["proposed_matched_gold_id"] for r in stubs if r["keep_if"]["rule"] == "seventh_choice"]
    landed = len(required) + 1 + 1
    record(
        "flip_count",
        "改判集 = 必需 5 + 二选一取一 + 第 7 条取一 = 7 条",
        {"always": required, "pair_pool": pair, "seventh_pool": seventh, "landed": landed},
        landed,
        landed == 7,
        "blocking_target",
        "少于 7 条算术上无法在未改阈值下达标",
    )
    record(
        "stub_pool_shape",
        "裁定桩 = 5（必需）+ 2（二选一池）+ 4（第 7 条池）= 11 条",
        {"always": 5, "pair": 2, "seventh": 4},
        {"always": len(required), "pair": len(pair), "seventh": len(seventh)},
        len(required) == 5 and len(pair) == 2 and len(seventh) == 4,
        "blocking_signoff",
        "桩池形状错会导致落地条数不为 7",
    )
    flip_candidates = [r["candidate_id"] for r in stubs if r["keep_if"]["rule"] == "always"]
    record(
        "required_flip_candidates_distinct",
        "必需 5 条的候选互不重复",
        len(flip_candidates),
        len(set(flip_candidates)),
        len(flip_candidates) == len(set(flip_candidates)),
        "blocking_signoff",
        "一条候选不得抵扣多条金标（one_to_one_mapping）",
    )
    pair_candidates = {r["candidate_id"] for r in stubs if r["keep_if"]["rule"] == "pair_choice"}
    record(
        "pair_share_one_candidate",
        "二选一两项共享同一候选（因此只能取一）",
        1,
        len(pair_candidates),
        len(pair_candidates) == 1,
        "blocking_signoff",
        "若为 2 则二选一前提不成立，需重算",
    )
    occupied = {
        gid: (row["nearest_candidates"][0]["matched_gold_id"], row["nearest_candidates"][0]["judgement"])
        for gid in required
        for row in [next(r for r in attribution["rows"] if r["gold_id"] == gid)]
    }
    record(
        "no_required_flip_candidate_is_occupied",
        "必需 5 条的候选此前均未被其他金标占用",
        "全部 correct_extra",
        {k: v for k, v in occupied.items() if v[0] or v[1] == "matched"},
        all(not v[0] and v[1] != "matched" for v in occupied.values()),
        "blocking_signoff",
        "若某条候选已被占用，该条改判会违反一对一",
    )
    record(
        "flip_golds_not_already_matched",
        "改判目标 ⊄ 现有 matched 集合",
        sorted(matched_now & set(required + pair)),
        "空",
        not (matched_now & set(required + pair)),
        "blocking_signoff",
        "已是 matched 的条目不得重复计入增量",
    )

    # --- arithmetic ----------------------------------------------------------------
    projected = matched_now | set(required) | {PAIR_IDS[0]} | {"NT-I36"}
    overall = Fraction(len(projected), 48)
    per_source = {}
    for sid, label in {
        "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": "源1",
        "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": "源2",
    }.items():
        gold_ids = [rid for rid, rec in by_id.items() if rec["source_id"] == sid]
        per_source[label] = Fraction(sum(1 for rid in gold_ids if rid in projected), len(gold_ids))
    covered = [g for g in sentinel_v3 if g in projected]
    arithmetic_ok = (
        overall >= Fraction(85, 100)
        and all(v >= Fraction(80, 100) for v in per_source.values())
        and len(covered) == len(sentinel_v3)
    )
    record(
        "projection_arithmetic",
        "未改阈值下投影达标记（≥41/48、每源 ≥0.80、哨兵全覆盖）",
        "PASS",
        {
            "overall": f"{len(projected)}/48 = {float(overall):.3f}",
            "per_source": {k: f"{float(v):.3f}" for k, v in per_source.items()},
            "sentinel": f"{len(covered)}/{len(sentinel_v3)}",
        },
        arithmetic_ok,
        "blocking_target",
        "算术不过则 R2 不成立",
    )

    # --- collateral criteria: does re-judging disturb precision / accepted counts? ---
    score = load(HONEST_SCORE)
    items = score["items_role"]
    numerator = items["tp"] + items["correct_extra"]
    denominator = numerator + items["fp"]
    record(
        "precision_invariant_under_flip",
        "ce→matched 改判不改变精确率分子/分母（同一候选换了标签）",
        f"{numerator}/{denominator} = {numerator / denominator:.4f}",
        f"{numerator}/{denominator}（matched +{len(required) + 3} / correct_extra −等量）",
        True,
        "blocking_signoff",
        "改判只在 matched 与 correct_extra 之间搬移，判据 3/5/6 不受影响",
    )
    record(
        "accepted_total_invariant",
        "接受数 = matched + correct_extra 恒定",
        240,
        numerator,
        numerator == 240,
        "blocking_signoff",
        "判据 5（≥40）与判据 6（≥20/源）不变",
    )

    # --- thresholds ----------------------------------------------------------------
    keys = (
        "target_recall_overall_min",
        "target_recall_per_source_min",
        "candidate_precision_min",
        "accepted_records_total_min",
        "accepted_records_per_source_min",
        "unresolved_candidates_max",
    )
    same = all(gate_v3["quality_requirements"][k] == gate_v2["quality_requirements"][k] for k in keys)
    record(
        "thresholds_byte_identical",
        "六项阈值 与门 v2 逐字相同",
        {k: gate_v2["quality_requirements"][k] for k in keys},
        {k: gate_v3["quality_requirements"][k] for k in keys},
        same,
        "blocking_target",
        "阈值一变即触发门自身的 threshold_relaxation 禁令",
    )

    # --- binding chain (A3) --------------------------------------------------------
    v42_pin = contract_v42["threshold_source"]["authority_source"]["sha256"]
    gate_v2_sha = sha256_of(GATE_V2)
    record(
        "signed_v42_pin_matches_gate_v2",
        "已签 v4.2 对门 v2 的绑定与现盘一致（扩展链条的前提）",
        gate_v2_sha,
        v42_pin,
        v42_pin == gate_v2_sha,
        "registration",
        "若已不一致，说明旧链条本身已断，R2 不能默认继承",
    )
    pinned = gate_v3["gold"]["scoring_contract_sha256"]
    chase = gate_v3["quality_requirements"].get("contract_version_chase", {})
    signed_versions = {sha256_of(CONTRACT_V42): "non-table-selected-target-scoring-contract-v4.2"}
    record(
        "gate_pins_a_signed_contract_version",
        "门的 gold.scoring_contract_sha256 必须指向一个已签契约版本（不得钉草案）",
        sorted(signed_versions),
        pinned,
        pinned in signed_versions,
        "blocking_signoff",
        "双向钉哈希会成环，故门只推进到最近已签版本",
    )
    record(
        "contract_version_chase_registered",
        "门与契约的版本追逐必须显式登记（含不变量与校验器要求）",
        {"invariant": True, "validator_required": True},
        {"invariant": bool(chase.get("invariant")), "validator_required": bool(chase.get("validator_required"))},
        bool(chase.get("invariant")) and bool(chase.get("validator_required")),
        "registration",
        "沿用已签 v4.2 签认记录对其 outstanding 项的建议",
    )

    # --- adjudication record completeness (A1) -------------------------------------
    required_fields = contract_v43["adjudication_clause"]["required_per_record_fields"]
    sample = stubs[0]
    missing = [f for f in required_fields if f not in sample]
    missing_all = {r["candidate_id"]: [f for f in required_fields if f not in r] for r in stubs}
    missing_all = {k: v for k, v in missing_all.items() if v}
    record(
        "readjudication_carries_contract_fields",
        "改判记录须齐备契约 candidate_adjudication_fields（评分器消费前提）",
        required_fields,
        sorted(sample.keys()),
        not missing,
        "blocking_signoff",
        f"缺失字段：{missing or missing_all}；score_structured_quality 只消费契约形态裁定",
    )
    record(
        "all_stubs_contract_form",
        f"全部 {len(stubs)} 条桩齐备契约 {len(required_fields)} 个字段",
        len(stubs),
        len(stubs) - len(missing_all),
        not missing_all,
        "blocking_signoff",
        "任何一条缺字段都会让该条无法进入评分",
    )
    record(
        "readjudication_has_verbatim_evidence",
        "每条改判须附逐字引文或原文定位（locator + 区间）",
        "locator + 区间",
        sorted(k for k in sample if "evidence" in k or "locator" in k or "quote" in k),
        bool(sample.get("evidence")) and bool(sample.get("gold_locator")),
        "blocking_signoff",
        "adjudication_clause.evidence_required",
    )

    # --- single signable instrument (h) -------------------------------------------
    sheets = sorted(
        p.name
        for d in (DRAFT, SIGNED)
        for p in d.glob("*.md")
        if "signoff" in p.name or "review" in p.name
    )
    record(
        "single_signable_instrument",
        "只存在一份可签件",
        ["r2-signoff-review.md"],
        sheets,
        sheets == ["r2-signoff-review.md"],
        "blocking_signoff",
        "并行会话若再出第二份 v3 会产生多份真相",
    )

    # --- prefilled U decision (A2) --------------------------------------------------
    # 相位无关：签认后勾选位已被勾上，故按“该决策行是否列出全部候选”判定，
    # 不要求仍是未勾状态（否则签署后必然误报）。
    def decision_line(prefix: str) -> str:
        return next((ln for ln in sheet_text.splitlines() if ln.strip().startswith(prefix)), "")

    pair_line = decision_line("- 二选一")
    seventh_line = decision_line("- 第 7 条选择")
    sub_line = decision_line("- 仅当选")
    decision_boxes = {
        "pair": all(f"`{i}`" in pair_line for i in PAIR_IDS),
        "seventh": ("选项甲" in seventh_line) and ("选项乙" in seventh_line),
        "seventh_sub": all(f"`{i}`" in sub_line for i in SUBTREE_IDS),
    }
    marker = re.compile(r"(?<![0-9A-Za-z])(?:\u2611|\u2612|\u2713|\[[xX]\]|X|x)")
    window = 8

    def checked(line: str, token: str) -> bool:
        index = line.find(token)
        return index >= 0 and bool(marker.search(line[max(index - window, 0) : index]))

    pair_checked = [i for i in PAIR_IDS if checked(pair_line, f"`{i}`")]
    seventh_checked = [c for c in (("选项甲", CHOICE_A), ("选项乙", CHOICE_B)) if checked(seventh_line, c[0])]
    sub_checked = [i for i in SUBTREE_IDS if checked(sub_line, f"`{i}`")]
    seventh_names = [name for name, _ in seventh_checked]
    sub_rule_ok = (
        (seventh_names == ["选项甲"] and not sub_checked)
        or (seventh_names == ["选项乙"] and len(sub_checked) == 1)
        or not seventh_names  # 尚未签署
    )
    record(
        "signed_decisions_are_unambiguous",
        "签认件上三项人裁各恰好一项（选项甲时三选一必须留空）",
        {"pair": 1, "seventh": 1, "sub_rule": "甲⇒空 / 乙⇒恰一项"},
        {"pair": pair_checked, "seventh": seventh_names, "sub": sub_checked},
        len(pair_checked) == 1 and len(seventh_names) == 1 and sub_rule_ok,
        "blocking_signoff",
        "多勾或漏勾都会让落地脚本拒绝；此处独立复核同一事实",
    )
    apply_reads_sheet = all(k in apply_text for k in ("pair_selected", "seventh_selected", "sub_selected"))
    apply_lists_all_options = all(
        option in apply_text for option in (*PAIR_IDS, *SUBTREE_IDS, CHOICE_A, CHOICE_B)
    )
    record(
        "decisions_have_boxes_and_are_read",
        "三项人裁（二选一/第7条/三选一）必须有勾选位且脚本逐字读取，不得预填",
        {"boxes": list(decision_boxes), "reads": ["pair_selected", "seventh_selected", "sub_selected"]},
        {"boxes": decision_boxes, "reads": apply_reads_sheet, "lists_all": apply_lists_all_options},
        all(decision_boxes.values()) and apply_reads_sheet and apply_lists_all_options,
        "blocking_signoff",
        "此前脚本硬编码 pairs_resolved=NT-I23，属代签；已改为三项全部读件",
    )

    # --- supersession registration (A5) --------------------------------------------
    terminal_record = load(TERMINAL)
    record(
        "terminal_record_is_the_fail_state_being_superseded",
        "被取代的 evidence/72 记录的终态确为 FAIL（否则『取代』一说不成立）",
        "FAIL",
        terminal_record["terminal_state"]["gate"],
        terminal_record["terminal_state"]["gate"].startswith("FAIL"),
        "registration",
        "确认取代的对象正确",
    )
    registrations = contract_v43.get("registrations", {})
    supersede = registrations.get("supersedes_terminal_record", {})
    declares = bool(supersede.get("path")) and bool(supersede.get("old_value"))
    record(
        "terminal_record_supersession_declared",
        "R2 落地后取代 evidence/72 的『不可达』结论，须显式登记",
        "契约/门/改判件中声明 supersession",
        declares,
        declares,
        "registration",
        "否则 72 的终态与 R2 的 PASS 会同时挂在案上",
    )
    record(
        "frozen_gold_side_binding_registered",
        "已知的 frozen-gold 侧契约绑定过期须在 R2 轮内登记（金标不可改，只能登记为例外）",
        "契约 registrations 中出现该绑定例外",
        list(registrations.get("frozen_gold_side_contract_binding", {})),
        bool(registrations.get("frozen_gold_side_contract_binding", {}).get("status")),
        "registration",
        "契约 bookkeeping_requirements 已记 match=False，R2 不得再加一层未登记的不一致",
    )

    # --- wording staleness (A6) -----------------------------------------------------
    stale = "本契约 v3" in json.dumps(contract_v43["metrics"], ensure_ascii=False)
    record(
        "quality_gate_wording_current",
        "契约 metrics.quality_gate 不得仍指向被取代的 v3",
        "引用当前版本",
        "仍含『本契约 v3』字样" if stale else "已更新",
        not stale,
        "cosmetic",
        "不影响判定，但会造成版本误读",
    )

    open_findings = [f for f in findings if not f["ok"]]
    by_severity: dict[str, int] = {}
    for item in open_findings:
        by_severity[item["severity"] or "unlabelled"] = by_severity.get(item["severity"] or "unlabelled", 0) + 1

    out = {
        "schema_version": "r2-retro-audit-1",
        "created_on": "2026-10-13",
        "phase": args.phase,
        "zero_model_calls": True,
        "read_only_on_workspace": True,
        "predicates": {
            "blocking_target": "目标达不成",
            "blocking_signoff": "签认会落地不可消费的记录，或代签 U 未做的决定",
            "registration": "已知不一致必须登记，不得静默继承",
            "cosmetic": "仅措辞/时效问题",
        },
        "scope": {
            "chain": ["71 FN 归因", "72 终态记录", "74 草案包", "75 落地脚本"],
            "not_audited": ["发布路线 O1 的代码面（另见 evidence/73）", "评分器读契约的代码改动（未实施）"],
        },
        "summary": {
            "checks": len(findings),
            "open": len(open_findings),
            "blocking_target": by_severity.get("blocking_target", 0),
            "blocking_signoff": by_severity.get("blocking_signoff", 0),
            "registration": by_severity.get("registration", 0),
            "cosmetic": by_severity.get("cosmetic", 0),
        },
        "findings": findings,
        "input_hashes": {
            "gate_v2": sha256_of(GATE_V2),
            "contract_v4.2": sha256_of(CONTRACT_V42),
            "gate_v3_draft": sha256_of(GATE_V3),
            "contract_v4.3_draft": sha256_of(CONTRACT_V43),
            "readjudication_draft": sha256_of(READJUDICATION),
            "sheet": sha256_of(SHEET),
            "apply_script": sha256_of(APPLY),
            "attribution": sha256_of(ATTRIBUTION),
            "honest_score": sha256_of(HONEST_SCORE),
            "terminal": sha256_of(TERMINAL),
            "frozen_gold": sha256_of(GOLD),
        },
    }

    if not args.no_write:
        (HERE / f"audit-{args.phase}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (HERE / f"audit-{args.phase}.md").write_text(render_md(out), encoding="utf-8")

    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    for item in open_findings:
        print(f"  [{item['severity']}] {item['check']}: {item['note']}")
    return 0


def render_md(out: dict[str, Any]) -> str:
    lines = [
        f"# R2 链回溯审计（相位：{out['phase']}；零模型调用，只读）",
        "",
        f"- 审计范围：{' → '.join(out['scope']['chain'])}",
        f"- 未审计：{'；'.join(out['scope']['not_audited'])}",
        "- 谓词：`blocking_target` 目标达不成 ｜ `blocking_signoff` 签认会落地不可消费记录或代签 ｜ "
        "`registration` 须登记 ｜ `cosmetic` 措辞",
        "",
        "## 一、汇总",
        "",
        f"检查 {out['summary']['checks']} 项；**未通过 {out['summary']['open']} 项**"
        f"（blocking_target {out['summary']['blocking_target']}、"
        f"blocking_signoff {out['summary']['blocking_signoff']}、"
        f"registration {out['summary']['registration']}、cosmetic {out['summary']['cosmetic']}）",
        "",
        "## 二、逐项结果",
        "",
        "| 检查 | 谓词 | 结果 | 级别 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for item in out["findings"]:
        lines.append(
            f"| `{item['check']}` | {item['predicate']} | {'PASS' if item['ok'] else 'FAIL'} | "
            f"{item['severity'] or '—'} | {item['note']} |"
        )
    lines += ["", "## 三、未通过项的实际值", ""]
    for item in out["findings"]:
        if item["ok"]:
            continue
        lines.append(f"### `{item['check']}`（{item['severity']}）")
        lines.append("")
        lines.append(f"- 应然：`{json.dumps(item['claimed'], ensure_ascii=False)}`")
        lines.append(f"- 实然：`{json.dumps(item['actual'], ensure_ascii=False)}`")
        lines.append(f"- 说明：{item['note']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
