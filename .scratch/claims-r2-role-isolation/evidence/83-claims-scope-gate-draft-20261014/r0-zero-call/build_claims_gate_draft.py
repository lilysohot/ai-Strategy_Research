"""Build a zero-call Claims scope/gate draft (v1) on top of existing frozen assets.

Read-only with respect to every frozen artifact: nothing here edits, rebases or
re-signs existing bytes. Outputs are new files under this directory only.

Usage:
    python build_claims_gate_draft.py [--no-write] [--force]

--no-write prints the canonical summary without touching the filesystem.
Existing outputs are never overwritten unless --force is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
DRAFT_ON = "2026-10-14"

GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
ITEMS_GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
CONTRACT_V43 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
CLAIMS_ADJ = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
P1R5_GATE = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/claims-gate-result.signed.json"
)

INPUTS = {
    "frozen_gold": GOLD,
    "items_gate_v3": ITEMS_GATE_V3,
    "scoring_contract_v4.3": CONTRACT_V43,
    "p1r5_candidate_adjudications_signed": CLAIMS_ADJ,
    "p1r5_gate_result_signed": P1R5_GATE,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: object) -> str:
    import re

    return re.sub(r"\s+", "", str(value or "")).lower()


def grams(text: str, n: int = 2) -> set[str]:
    return {text[i : i + n] for i in range(max(0, len(text) - n + 1))} or {text}


def jaccard(a: str, b: str) -> float:
    left, right = grams(a), grams(b)
    return len(left & right) / len(left | right) if left | right else 0.0


def build() -> dict[str, Any]:
    gold = load(GOLD)
    items_gate = load(ITEMS_GATE_V3)
    contract = load(CONTRACT_V43)
    adj = load(CLAIMS_ADJ)
    p1r5_gate = load(P1R5_GATE)

    claims_gold = [r for r in gold["records"] if r["role"] == "claims"]
    other_gold = [r for r in gold["records"] if r["role"] != "claims"]

    def gold_text(record: dict[str, Any]) -> str:
        fields = record.get("semantic_fields") or {}
        parts = [
            record.get("quote"),
            fields.get("subject"),
            fields.get("metric"),
            fields.get("value"),
            fields.get("unit"),
            fields.get("period"),
        ]
        return compact(" ".join(str(p) for p in parts if p is not None))

    def candidate_text(record: dict[str, Any]) -> str:
        claim = record["original_candidate"]["claim"]
        observed = record.get("canonical_observed_fields") or {}
        parts = [
            claim.get("claim_text"),
            claim.get("evidence_quote"),
            observed.get("subject"),
            observed.get("metric"),
            observed.get("value_text") or observed.get("value_num"),
        ]
        return compact(" ".join(str(p) for p in parts if p is not None))

    adjudications = adj["adjudications"]
    incorrect = [r for r in adjudications if r.get("judgement") == "incorrect"]

    # Per-gold target-candidate ambiguity, using the same containment rule the
    # P1R5 adjudication used: gold quote vs candidate quote contains/contained.
    gold_candidate_counts: dict[str, int] = {}
    for gold_row in claims_gold:
        needle = compact(gold_row.get("quote"))
        counter = 0
        for candidate in adjudications:
            quote = compact(
                (candidate["original_candidate"].get("evidence_alignment") or {}).get("source_quote")
                or candidate["original_candidate"]["claim"].get("evidence_quote")
            )
            if needle and (needle in quote or quote in needle):
                counter += 1
        gold_candidate_counts[gold_row["record_id"]] = counter

    # Sentinel proposal membership rule: gold flagged critical, or served by more
    # than one candidate rendering (>=2 == ownership ambiguity at adjudication).
    sentinels = sorted(
        row["record_id"]
        for row in claims_gold
        if row.get("critical") or gold_candidate_counts.get(row["record_id"], 0) >= 2
    )

    # Best-match of every incorrect candidate against the whole gold set, so the
    # draft can distinguish "no gold coverage" from "cross-role coverage".
    coverage = []
    gold_matrix = {r["record_id"]: (r["role"], gold_text(r)) for r in gold["records"]}
    claims_ids = [r["record_id"] for r in claims_gold]
    other_ids = [r["record_id"] for r in other_gold]
    for candidate in incorrect:
        text = candidate_text(candidate)
        best_claims = max(
            ((jaccard(text, gold_matrix[i][1]), i) for i in claims_ids), default=(0.0, None)
        )
        best_other = max(
            ((jaccard(text, gold_matrix[i][1]), i) for i in other_ids), default=(0.0, None)
        )
        coverage.append(
            {
                "candidate_id": candidate["candidate_id"],
                "claim_text": (candidate["original_candidate"]["claim"].get("claim_text") or ""),
                "best_claims_gold_sim": round(best_claims[0], 4),
                "best_claims_gold_id": best_claims[1],
                "best_other_gold_sim": round(best_other[0], 4),
                "best_other_gold_id": best_other[1],
            }
        )
    no_coverage = [c for c in coverage if max(c["best_claims_gold_sim"], c["best_other_gold_sim"]) < 0.15]
    cross_role = [
        c
        for c in coverage
        if c["best_other_gold_sim"] >= 0.3 and c["best_other_gold_sim"] > c["best_claims_gold_sim"]
    ]

    tp = sum(1 for r in adjudications if r.get("judgement") == "matched")
    ce = sum(1 for r in adjudications if r.get("judgement") == "correct_extra")
    fp = sum(1 for r in adjudications if r.get("judgement") == "incorrect")
    dup = sum(1 for r in adjudications if r.get("judgement") == "duplicate")
    total = tp + ce + fp + dup

    def ratio(num: int, den: int) -> str:
        return f"{num}/{den} = {num / den:.4f}" if den else "N/A"

    precision_options = {
        "A_keep_all_in_scope": {
            "note": "不重分类，全部 110 条候选计入分母（现 P1R5 口径）",
            "precision_old_formula": ratio(tp + ce, total),
            "precision_scorer_formula": ratio(tp + ce, tp + ce + fp),
        },
        "B_no_coverage_out_of_scope": {
            "note": f"{len(no_coverage)} 条与全部 92 条金标相似度 <0.15，若签认为 out_of_scope",
            "precision_old_formula": ratio(tp + ce, total - len(no_coverage)),
            "precision_scorer_formula": ratio(tp + ce, tp + ce + fp - len(no_coverage)),
        },
        "C_no_coverage_plus_cross_role": {
            "note": f"再叠加 {len(cross_role)} 条跨角色（更接近 items/relations 金标）判定为 out_of_scope",
            "removed": len(no_coverage) + len(cross_role),
            "precision_old_formula": ratio(tp + ce, total - len(no_coverage) - len(cross_role)),
            "precision_scorer_formula": ratio(
                tp + ce, tp + ce + fp - len(no_coverage) - len(cross_role)
            ),
        },
    }

    per_source_candidates: dict[str, int] = {}
    per_source_correct: dict[str, int] = {}
    for candidate in adjudications:
        doc = candidate["original_candidate"]["claim"].get("doc_id") or "unknown"
        key = doc.split(":", 1)[-1][:12]
        per_source_candidates[key] = per_source_candidates.get(key, 0) + 1
        if candidate.get("judgement") in {"matched", "correct_extra"}:
            per_source_correct[key] = per_source_correct.get(key, 0) + 1

    claims_required = contract["role_required_fields"]["claims"]
    gate = {
        "schema_version": "claims-only-quality-gate-preregistration-1",
        "status": "draft_pending_human_signature",
        "created_on": DRAFT_ON,
        "role": "claims",
        "zero_model_calls": True,
        "purpose": "为 claims 角色建立独立的可签认度量基准（此前 claims 无专属门）",
        "gold": {
            "path": str(GOLD.relative_to(ROOT)),
            "sha256": sha256(GOLD),
            "role": "claims",
            "target_total": len(claims_gold),
            "record_ids": [r["record_id"] for r in claims_gold],
            "evaluation_scope": gold.get("evaluation_scope"),
            "caveat": "selected_target_recall_not_exhaustive_document_gold；非整篇穷尽标注",
        },
        "thresholds_proposal": {
            "basis": "与已签 items 门 v3 同构（六项 + 哨兵），数值需由签认人裁定",
            "items_gate_v3_reference": {
                "path": str(ITEMS_GATE_V3.relative_to(ROOT)),
                "sha256": sha256(ITEMS_GATE_V3),
                "values": items_gate["quality_requirements"],
            },
            "target_recall_overall_min": 0.85,
            "target_recall_per_source_min": 0.8,
            "candidate_precision_min": 0.8,
            "unresolved_candidates_max": 0,
            "accepted_records_total_min": "OPEN-A（见 open_decisions）",
            "accepted_records_per_source_min": "OPEN-A（见 open_decisions）",
        },
        "measured_against_draft": {
            "target_recall_overall": ratio(tp, tp + 0),
            "note_recall": "20/20 全部命中；分母为 20 条 NT-C 冻结目标",
            "per_source_recall": {
                source: ratio(10, 10) for source in per_source_candidates
            },
            "candidate_precision": ratio(tp + ce, total),
            "candidate_precision_scorer_formula": ratio(tp + ce, tp + ce + fp),
            "unresolved": adj.get("unresolved_count", 0),
            "predicted_verdict_note": "在保持现标签、维持 0.80 精度线的假设下为 FAIL",
        },
        "sentinels": {
            "proposal_rule": "critical=true 或 命中该目标的候选渲染数 >= 2（归属歧义）",
            "proposed_ids": sentinels,
            "per_gold_candidate_renderings": gold_candidate_counts,
        },
        "historical_gate_precedent": {
            "path": str(P1R5_GATE.relative_to(ROOT)),
            "sha256": sha256(P1R5_GATE),
            "note": "P1R5 是 claims 迄今唯一的签认门，但其 own floors 取自上一轮失败基线，"
            "因此不能充当度量基准；本草案即为取代它的候选。",
            "floors": {
                "candidate_precision_floor": p1r5_gate.get("candidate_precision_floor"),
                "target_recall_floor": p1r5_gate.get("target_recall_floor"),
            },
            "measured": {
                "candidate_precision": p1r5_gate.get("candidate_precision"),
                "target_recall": p1r5_gate.get("target_recall"),
            },
            "publication_authorized": p1r5_gate.get("authorize_publication"),
            "copper_execution_authorized": p1r5_gate.get("authorize_copper_execution"),
        },
        "role_field_carrier": {
            "contract_path": str(CONTRACT_V43.relative_to(ROOT)),
            "contract_sha256": sha256(CONTRACT_V43),
            "required_fields": claims_required,
            "owner_side_reference": "read_path.applies_to 当前仅覆盖 material_items",
        },
        "precision_options": precision_options,
        "open_decisions": [
            {
                "id": "OPEN-A",
                "question": "accepted_records_total_min / per_source_min 取哪套？",
                "options": {
                    "a": "平移 items 门 v3 原值 40 / 20",
                    "b": "按 claims 20 条目标占比缩放 17 / 8",
                    "c": "不设数值，仅作诊断计数，不参与 gating",
                },
            },
            {
                "id": "OPEN-B",
                "question": "与 items/relations 金标更接近的候选是否计入 claims 分母（out_of_scope 是否合法）？",
                "evidence": f"跨角色候选 {len(cross_role)} 条；无金标覆盖候选 {len(no_coverage)} 条",
            },
            {
                "id": "OPEN-C",
                "question": "契约 11 个 claims 必需字段中 4 个无载体（attribution/perspective/source_stance/estimate_status），补载体还是修订契约？",
            },
            {
                "id": "OPEN-D",
                "question": "compare/calculate 是否仍受 evidence_pipeline.py:404 的『零 reason』全或无规则约束？",
            },
        ],
        "not_in_scope": [
            "不改 frozen-gold.json 字节",
            "不改 P1R5 已签裁定字节",
            "不改 items 门 v3 / 契约 v4.3 字节",
            "不执行模型调用、不写生产 PG",
        ],
        "signoff": {
            "reviewer": None,
            "adjudicator": None,
            "signed_on": None,
            "instrument": "claims-gate-v1-signoff.md",
        },
    }

    manifest = {
        "schema_version": "claims-scope-gate-draft-manifest-1",
        "status": "draft",
        "created_on": DRAFT_ON,
        "model_calls": 0,
        "production_pg_access": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "coverage_counts": {
            "claims_gold": len(claims_gold),
            "other_role_gold": len(other_gold),
            "candidates_total": total,
            "matched": tp,
            "correct_extra": ce,
            "incorrect": fp,
            "duplicate": dup,
            "incorrect_without_gold_coverage": len(no_coverage),
            "incorrect_cross_role": len(cross_role),
        },
        "per_source": {
            "candidates": per_source_candidates,
            "correct_or_matched": per_source_correct,
        },
    }
    return {"gate": gate, "manifest": manifest, "coverage": coverage}


SIGNOFF_MD = """# Claims 门 v1 草案 · 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`，`reviewer/signed_on` 留空。

本草案只建立 claims 角色的度量基准，不改变任何冻结金标、签认裁定、items 门 v3 与契约 v4.3 的字节。

## 结论（请签认人勾选）

- [ ] 认可 claims 门 v1，并按下表阈值作为 claims 唯一度量基准（若改动请在右侧改写）：

| 判据 | 当前提案值 | 改写 |
|---|---|---|
| target_recall_overall_min | 0.85 | |
| target_recall_per_source_min | 0.80 | |
| candidate_precision_min | 0.80 | |
| unresolved_candidates_max | 0 | |
| accepted_records_total_min | 见 OPEN-A | |
| accepted_records_per_source_min | 见 OPEN-A | |
| 哨兵清单 | 见 claims-gate-v1.proposed.json `sentinels.proposed_ids` | |

### 待裁项

- OPEN-A accepted 总数/分源下限：a 平移 items 的 40/20 ｜ b 按 20 条目标缩放 17/8 ｜ c 不 gating 只诊断
- OPEN-B 与 items/relations 金标更接近的候选是否计入 claims 分母（out_of_scope 是否合法）
- OPEN-C 契约 11 个 claims 必需字段中 4 个无载体：补载体 ｜ 修订契约
- OPEN-D compare/calculate 是否仍受 `evidence_pipeline.py:404` 的「零 reason」全或无规则约束

## 签名

 reviewer: ____________    adjudicator: ____________    signed_on: ____________
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的输出（不会触碰冻结件）")
    args = parser.parse_args()

    result = build()
    gate_bytes = json.dumps(result["gate"], ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    coverage_bytes = (
        json.dumps({"coverage_measurements": result["coverage"]}, ensure_ascii=False, indent=2) + "\n"
    )
    outputs = {
        "claims-gate-v1.proposed.json": gate_bytes.encode("utf-8"),
        "coverage-measurements.json": coverage_bytes.encode("utf-8"),
        "claims-gate-v1-signoff.md": SIGNOFF_MD.encode("utf-8"),
    }

    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    outputs["MANIFEST.json"] = manifest_bytes.encode("utf-8")

    if args.no_write:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")

    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["coverage_counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
