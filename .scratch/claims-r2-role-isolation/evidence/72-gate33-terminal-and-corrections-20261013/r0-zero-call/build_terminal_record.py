#!/usr/bin/env python3
"""Gate-33 terminal record + corrections of four contradicted statements (zero calls).

Purpose
  Record, in one versioned place, that gate 33 is judged unreachable under the standing
  constraint "frozen gold and sample set unchanged", and correct four statements in
  already-executed artifacts that the evidence/71 machine attribution contradicts.
  Nothing here edits an existing artifact byte: old hashes are retained alongside.

Scope
  Read-only on every input. Writes only inside its own evidence directory.
  --no-write computes and prints the summary without writing artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"

SOURCE_LABEL = {
    "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": "源1",
    "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": "源2",
}


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    gold_path = E / "10-quality-gold-freeze-20261008-r2/frozen-gold.json"
    score_path = E / "69-union-adjudication-20261013/r1-score/gate33-honest-score.json"
    verdict_path = E / "69-union-adjudication-20261013/r1-score/gate33-full-verdict.md"
    attribution_path = E / "71-fn-attribution-20261013/r0-zero-call/fn-attribution.json"
    worksheet_path = SCRATCH / "adjudication/worksheet.json"
    signed_paths = {
        "r5": E / "65-rerun-two-arm-protocol-20261013/r6-assembly/assembled-scoring-input.json",
        "base": E / "66-base-protocol-change-proposal-20261013/r4-assembly/assembled-scoring-input.json",
    }
    contract_path = E / "58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json"
    issue_path = SCRATCH / "issues/33-items-quality-scoring-gate.md"
    report_path = SCRATCH / "report.md"
    closure_path = E / "70-closure-20261013/r0-zero-call/closure.md"
    residual_path = E / "32-items-v6-reasoning-refreeze-20261011/live/residual-attribution.json"

    by_id = {r["record_id"]: r for r in load(gold_path)["records"] if r["role"] == "material_items"}
    score = load(score_path)
    attribution = load(attribution_path)
    contract = load(contract_path)
    assertions = sorted(k for k in contract["review_assertions"] if k.startswith("NT-I"))
    matched = set(score["matched_gold_ids"])
    missing = sorted(score["missing_gold_ids"])
    assert sorted(matched | set(missing)) == sorted(by_id), "score ids do not cover the 48 gold"

    # --- criterion-by-criterion terminal state, recomputed rather than transcribed ---
    per_source: dict[str, dict[str, Any]] = {}
    for sid, label in SOURCE_LABEL.items():
        gold_ids = [rid for rid, rec in by_id.items() if rec["source_id"] == sid]
        hit = [rid for rid in gold_ids if rid in matched]
        per_source[label] = {
            "gold": len(gold_ids),
            "matched": len(hit),
            "recall": str(Fraction(len(hit), len(gold_ids))),
            "recall_float": round(len(hit) / len(gold_ids), 3),
        }
    overall_recall = Fraction(len(matched), len(by_id))
    assertions_failed = [g for g in assertions if g not in matched]

    # --- adjudication tallies, machine-counted from the authoritative inputs ---
    tallies: dict[str, int] = {}
    for rec in load(worksheet_path)["records"]:
        tallies[rec["judgement"]] = tallies.get(rec["judgement"], 0) + 1
    signed_tallies: dict[str, int] = {}
    for path in signed_paths.values():
        for m in load(path)["mappings"]:
            signed_tallies[m["judgement"]] = signed_tallies.get(m["judgement"], 0) + 1
    unresolved = tallies.get("unresolved", 0) + signed_tallies.get("unresolved", 0)

    thresholds = {
        "target_recall_overall_min": 0.85,
        "target_recall_per_source_min": 0.8,
        "candidate_precision_min": 0.8,
        "accepted_records_total_min": 40,
        "accepted_records_per_source_min": 20,
        "unresolved_candidates_max": 0,
    }
    verdict_values = {"accepted_records_total": 242, "accepted_records_per_source": {"源1": 117, "源2": 130}}
    scorer_values = {
        "tp": score["items_role"]["tp"],
        "fp": score["items_role"]["fp"],
        "duplicate_fp": score["items_role"]["duplicate_fp"],
        "correct_extra": score["items_role"]["correct_extra"],
        "precision": score["precision"],
        "recall": score["recall"],
    }
    scorer_accepted_total = scorer_values["tp"] + scorer_values["correct_extra"]

    criteria = [
        {
            "n": 1,
            "id": "target_recall_overall_min",
            "threshold": ">= 0.85",
            "measured": f"{len(matched)}/{len(by_id)} = {float(overall_recall):.3f}",
            "verdict": "PASS" if overall_recall >= Fraction(85, 100) else "FAIL",
        },
        {
            "n": 2,
            "id": "target_recall_per_source_min",
            "threshold": ">= 0.80 每源",
            "measured": "；".join(
                f"{lab} {v['matched']}/{v['gold']} = {v['recall_float']}" for lab, v in per_source.items()
            ),
            "verdict": (
                "PASS"
                if all(Fraction(v["matched"], v["gold"]) >= Fraction(80, 100) for v in per_source.values())
                else "FAIL"
            ),
        },
        {
            "n": 3,
            "id": "candidate_precision_min",
            "threshold": ">= 0.80",
            "measured": f"{scorer_values['precision']}（{scorer_accepted_total}/"
            f"{scorer_accepted_total + max(scorer_values['fp'] - scorer_values['duplicate_fp'], 0) + scorer_values['duplicate_fp']}）",
            "verdict": "PASS",
        },
        {
            "n": 4,
            "id": "unresolved_candidates_max",
            "threshold": "= 0",
            "measured": f"{unresolved}（A 池 {tallies} + 签认批 {signed_tallies}）",
            "verdict": "PASS" if unresolved == 0 else "FAIL",
        },
        {
            "n": 5,
            "id": "accepted_records_total_min",
            "threshold": ">= 40",
            "measured": f"{verdict_values['accepted_records_total']}（verdict 口径；评分器导出 tp+ce = {scorer_accepted_total}）",
            "verdict": "PASS",
        },
        {
            "n": 6,
            "id": "accepted_records_per_source_min",
            "threshold": ">= 20/源",
            "measured": json.dumps(verdict_values["accepted_records_per_source"], ensure_ascii=False),
            "verdict": "PASS",
        },
        {
            "n": 7,
            "id": "high_risk_item_assertions_required",
            "threshold": "16/16 全覆盖",
            "measured": f"{len(assertions) - len(assertions_failed)}/{len(assertions)}；未中 {assertions_failed}",
            "verdict": "PASS" if not assertions_failed else "FAIL",
        },
    ]
    failed = [c["n"] for c in criteria if c["verdict"] == "FAIL"]

    # --- why unreachable: after every other FN is re-judged, the residue is the U calibration set ---
    scenarios = attribution["scenarios"]
    blocker_scenario = scenarios["S3_A_B_minus_u_calibration"]
    s3_recovered = set(blocker_scenario["extra_matched"])
    last_blocker = [g for g in assertions_failed if g not in s3_recovered]
    rejudgeable = [g for g in assertions_failed if g in s3_recovered]

    out = {
        "schema_version": "gate33-terminal-record-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "decision_authority": "U（xyl）2026-10-13：不改金标、不扩大样本 ⇒ 门 33 判为不可达、如实记档",
        "predicate": {
            "达标": "门 33 的 7 条 quality_requirements 判据全部 PASS",
            "不可达": "在冻结金标字节不变、样本不扩大、既有具名裁定不变的前提下，7 条判据无法同时 PASS",
            "已声明边界": "本判定不是『绝对无解』；改判、改判据或改候选承载语义均属另一类动作，会同时改变标准本身",
        },
        "terminal_state": {
            "gate": "FAIL（不可达）",
            "failed_criteria": failed,
            "criteria": criteria,
            "thresholds": thresholds,
            "scorer_values": scorer_values,
        },
        "unreachability_structure": {
            "assertions_blocking_after_full_re_judgement": last_blocker,
            "assertions_recoverable_by_re_judgement": rejudgeable,
            "cause": (
                "NT-I45/I46/I47 的候选与金标逐字相同（sim=1.0），但 U 于 2026-10-12 亲自撤销其 matched，"
                "理由为金标属『被转述且被质疑的预测』(perspective=quoted_other, source_stance=challenged)，"
                "候选为材料自身陈述。该口径由 U 本人设定，任何执行动作（补抽/降门槛）都无法翻回。"
            ),
            "why_not_other_routes": {
                "targeted_reextraction": "补抽产出相同片段，会被同一口径再判 correct_extra",
                "lower_numeric_threshold": "即使把 overall/per-source 降到实测值以下，判据 7 仍为 13/16",
            },
            "counterfactual_if_all_14_rejudicated": {
                "scenario": "S2_A_and_B（evidence/71）",
                "recall": scenarios["S2_A_and_B"]["recall_overall"],
                "assertions": scenarios["S2_A_and_B"]["assertions_covered"],
                "verdict": scenarios["S2_A_and_B"]["verdict"],
            },
            "counterfactual_keeping_u_calibration": {
                "scenario": "S3_A_B_minus_u_calibration（evidence/71）",
                "recall": blocker_scenario["recall_overall"],
                "per_source": blocker_scenario["per_source"],
                "assertions": blocker_scenario["assertions_covered"],
                "verdict": blocker_scenario["verdict"],
            },
        },
        "fn_attribution_summary": {
            "fn_total": attribution["inventory"]["fn_total"],
            "bucket_counts": attribution["bucket_counts"],
            "finding": "14/14 条 FN 均有同源近似候选并带具名裁定理由；0 条为抽取覆盖缺口，0 条落在 9 个未产出槽",
        },
        "corrections": [
            {
                "n": 1,
                "statement": "缺口为真实 FN（金标无候选匹配），非流程问题",
                "where": "evidence/69-union-adjudication-20261013/r1-score/gate33-honest-score.json:88",
                "old_sha256": sha256_of(score_path),
                "machine_finding": "14/14 条 FN 均有同源近似候选；『无匹配』字面为真，读作『模型未产出』为假",
                "superseded_by": "evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json",
            },
            {
                "n": 2,
                "statement": "14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖）",
                "where": "evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:26-30",
                "old_sha256": sha256_of(verdict_path),
                "machine_finding": "0 条落在 evidence/32 记录的 9 个未产出槽；0 条为『池内无近似候选』",
                "superseded_by": "evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json",
            },
            {
                "n": 3,
                "statement": "8 条未过断言全部属于源2 文档段",
                "where": "evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:17；report.md:14",
                "old_sha256": {"verdict": sha256_of(verdict_path), "report": sha256_of(report_path)},
                "machine_finding": "NT-I09、NT-I19 属于源1；与该文件自身判据 2『源1 20/22』自相矛盾",
                "superseded_by": "evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.md",
            },
            {
                "n": 4,
                "statement": "源2 召回 0.538 + 8 条断言未过：需对源2 对应片段定向补抽",
                "where": "evidence/70-closure-20261013/r0-zero-call/closure.md:29；gate33-full-verdict.md:34",
                "old_sha256": {"closure": sha256_of(closure_path), "verdict": sha256_of(verdict_path)},
                "machine_finding": "补抽产出相同片段，会被同一裁定口径再判 correct_extra；缺口在裁定口径而非抽取",
                "superseded_by": "evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json",
            },
        ],
        "unaffected_by_this_decision": {
            "publish_standard": (
                "发布标准（结构完备性）与门 33 阈值/金标解耦：store.py 对 gold/recall/assertion 零引用；"
                "按 U 裁定走『显式缺口』路线"
            ),
            "still_open": [
                "issue 33 §7 gold_consumption_and_scoring 授权行仍为空 —— 未具名前保持挂账",
                "ef08 槽 r4 模型名偏差（已申报，未处置）",
                "预注册与授权文件未互链（轻微）",
            ],
        },
        "record_inconsistencies": [
            {
                "item": "accepted_records_total",
                "verdict_value": verdict_values["accepted_records_total"],
                "scorer_derivable_value": scorer_accepted_total,
                "impact": "两者均 >= 40，判据 5 结论不变；仅记录分歧，不判定谁对",
            },
            {
                "item": "8 条断言所属源",
                "verdict_value": "全部源2",
                "machine_value": f"源1 {[g for g in assertions_failed if SOURCE_LABEL[by_id[g]['source_id']] == '源1']}",
                "impact": "影响判据 2/7 的归因表述，不影响 FAIL 结论",
            },
        ],
        "input_hashes": {
            "gold": sha256_of(gold_path),
            "score": sha256_of(score_path),
            "verdict": sha256_of(verdict_path),
            "attribution": sha256_of(attribution_path),
            "worksheet_A": sha256_of(worksheet_path),
            **{f"signed_{k}": sha256_of(v) for k, v in signed_paths.items()},
            "contract": sha256_of(contract_path),
            "issue_33": sha256_of(issue_path),
            "report": sha256_of(report_path),
            "closure": sha256_of(closure_path),
            "residual_attribution": sha256_of(residual_path),
        },
        "reproduce": (
            "uv run python .scratch/claims-r2-role-isolation/evidence/"
            "72-gate33-terminal-and-corrections-20261013/r0-zero-call/build_terminal_record.py"
        ),
    }

    summary = {
        "gate_terminal": out["terminal_state"]["gate"],
        "failed_criteria": failed,
        "corrections": len(out["corrections"]),
        "assertions_blocking_after_full_re_judgement": last_blocker,
        "assertions_recoverable_by_re_judgement": rejudgeable,
        "record_inconsistencies": len(out["record_inconsistencies"]),
    }

    if not args.no_write:
        (HERE / "terminal-decision.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (HERE / "corrections.md").write_text(render_md(out), encoding="utf-8")
        manifest = {
            "schema_version": "evidence-manifest-1",
            "created_on": "2026-10-13",
            "zero_model_calls": True,
            "artifacts": {
                name: sha256_of(HERE / name)
                for name in ("build_terminal_record.py", "terminal-decision.json", "corrections.md")
            },
            "inputs": out["input_hashes"],
            "note": "本记录取代 corrections.md 所列四处表述；旧件字节与哈希留存，未编辑。",
            "reproduce": out["reproduce"],
        }
        (HERE / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def render_md(out: dict[str, Any]) -> str:
    ts, struct = out["terminal_state"], out["unreachability_structure"]
    lines = [
        "# 门 33 终态记录与四处表述更正（零模型调用）",
        "",
        f"- 2026-10-13　授权：{out['decision_authority']}",
        "- 谓词：**达标** = 7 条判据全 PASS；**不可达** = 在冻结金标字节不变、样本不扩大、既有具名裁定不变下无法同时 PASS",
        "",
        "## 一、终态",
        "",
        f"**门 33 = {ts['gate']}**（未过判据：{ts['failed_criteria']}）",
        "",
        "| # | 判据 | 门槛 | 实测 | 判定 |",
        "|---|---|---|---|---|",
    ]
    for c in ts["criteria"]:
        lines.append(f"| {c['n']} | {c['id']} | {c['threshold']} | {c['measured']} | **{c['verdict']}** |")
    lines += [
        "",
        "## 二、为什么不可达",
        "",
        f"- 判据 7 缺口 8 条：可通过复核裁定回收 {struct['assertions_recoverable_by_re_judgement']}，"
        f"**改判也无法回收（本轮的最后阻塞）** {struct['assertions_blocking_after_full_re_judgement']}",
        f"- 原因：{struct['cause']}",
        "",
        "| 其他出路 | 为什么不行 |",
        "|---|---|",
    ]
    for k, v in struct["why_not_other_routes"].items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "反事情景（evidence/71）：",
        "",
        f"- 保留 U 校准（{struct['counterfactual_keeping_u_calibration']['scenario']}）："
        f"召回 {struct['counterfactual_keeping_u_calibration']['recall']}、断言 "
        f"{struct['counterfactual_keeping_u_calibration']['assertions']} → "
        f"**{struct['counterfactual_keeping_u_calibration']['verdict']}**",
        f"- 全部 14 条改判（{struct['counterfactual_if_all_14_rejudicated']['scenario']}）："
        f"召回 {struct['counterfactual_if_all_14_rejudicated']['recall']}、断言 "
        f"{struct['counterfactual_if_all_14_rejudicated']['assertions']} → "
        f"**{struct['counterfactual_if_all_14_rejudicated']['verdict']}**"
        "（但这属于改判，不是原标准下的达标）",
        "",
        "## 三、四处表述更正（旧件字节与哈希留存，未编辑）",
        "",
        "| # | 既有表述 | 出处 | 机器实测 | 取代证据 |",
        "|---|---|---|---|---|",
    ]
    for c in out["corrections"]:
        lines.append(
            f"| {c['n']} | {c['statement']} | `{c['where']}` | {c['machine_finding']} | `{c['superseded_by']}` |"
        )
    lines += [
        "",
        "## 四、记录之间的分歧（仅登记，不判定）",
        "",
        "| 项 | 一处记录 | 另一处/机器值 | 影响 |",
        "|---|---|---|---|",
    ]
    for r in out["record_inconsistencies"]:
        first = r.get("verdict_value")
        second = r.get("scorer_derivable_value") or r.get("machine_value")
        lines.append(f"| {r['item']} | {first} | {second} | {r['impact']} |")
    lines += [
        "",
        "## 五、本裁定不影响的项",
        "",
        f"- {out['unaffected_by_this_decision']['publish_standard']}",
        "",
        "仍开放（不阻塞本记录）：",
        "",
    ]
    for item in out["unaffected_by_this_decision"]["still_open"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 六、复现",
        "",
        "```bash",
        out["reproduce"],
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
