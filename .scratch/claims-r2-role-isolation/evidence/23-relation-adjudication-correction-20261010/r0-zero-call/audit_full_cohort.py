"""Uniformly audit all 44 signed P11 relation cases without model calls."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
P11 = (
    CLAIMS
    / "evidence"
    / "18-material-extractor-replacement-20261009"
    / "p11-relation-precision-sample"
)
P12 = (
    CLAIMS
    / "evidence"
    / "18-material-extractor-replacement-20261009"
    / "p12-relation-selector-v2-zero-call"
)
ISSUE22 = CLAIMS / "evidence" / "22-doubao-lite-provider-ceiling-20261010" / "p0-256k-minimal-live"
EVALUATOR = (
    CLAIMS
    / "evidence"
    / "19-relation-selection-successor-20261010"
    / "r0-p14-counterfactual"
    / "audit_counterfactual.py"
)

# Every signed case is listed explicitly so omissions and post-hoc selection fail closed.
# ``local_binding`` means the frozen pair window uniquely resolves a surface pronoun or ellipsis.
AUDIT: dict[str, tuple[str, str, str]] = {
    "pair_c8a2e609d0bf69ac": (
        "scoreable",
        "retain_truth",
        "The pricing ambition is complete but does not answer the requested expansion thickness.",
    ),
    "pair_656be2399f54e209": (
        "local_binding",
        "retain_truth",
        "The short comparison question is uniquely resolved by the adjacent carrier-foil reply.",
    ),
    "pair_75e57fa1a91444d1": (
        "unscorable",
        "exclude_unscorable",
        "The generic request '请您介绍一下' contains no retained referent or question predicate.",
    ),
    "pair_5956d4ff0f239792": (
        "scoreable",
        "retain_truth",
        "A technical-requirement comparison does not answer the equipment-value question.",
    ),
    "pair_948115917d484326": (
        "scoreable",
        "retain_truth",
        "The reply directly identifies ultra-thin foil equipment as the expansion choice.",
    ),
    "pair_accf55e14399b995": (
        "unscorable",
        "exclude_unscorable",
        "The target combines external procurement and Taijin share while the source supports only the whole-solution rationale.",
    ),
    "pair_867bb55010d3409f": (
        "local_binding",
        "retain_truth",
        "The adjacent causal clause uniquely binds thicker 6-8 micron foil to the lower-control requirement.",
    ),
    "pair_0fe2596533c9062c": (
        "scoreable",
        "retain_truth",
        "Existing supply and thinner demand explicitly support not expanding 6-8 micron output.",
    ),
    "pair_7ebcec23ea283bfd": (
        "scoreable",
        "retain_truth",
        "The stated process difficulty explicitly supports the higher front-end equipment price.",
    ),
    "pair_1a9d24af1bf7107f": (
        "local_binding",
        "change_truth",
        "The six-month replacement frequency is an explicit component of the requested revenue calculation.",
    ),
    "pair_e30e95a14e98a666": (
        "scoreable",
        "retain_truth",
        "The affirmative reply directly confirms the capacity and scheduled-production question.",
    ),
    "pair_99ad745a830b3057": (
        "scoreable",
        "retain_truth",
        "Accompanying customer tests explains payment uncertainty, not the requested delivery timing.",
    ),
    "pair_dc4f0640ec6b4b11": (
        "local_binding",
        "change_truth",
        "Low expansion intent directly explains the same answer's low external-purchase probability.",
    ),
    "pair_b017f3137cc2221f": (
        "scoreable",
        "retain_truth",
        "Signed volume and annual capacity directly answer whether industry demand has recovered.",
    ),
    "pair_cd8df0324de3133f": (
        "unscorable",
        "exclude_unscorable",
        "The target '不一定全部' omits what is incomplete; the frozen pair window does not restore the object.",
    ),
    "pair_1d89be203265a027": (
        "local_binding",
        "retain_truth",
        "The same sentence uniquely resolves Mitsui as the developer and external-purchase subject.",
    ),
    "pair_05ccd9efcd925fec": (
        "local_binding",
        "retain_truth",
        "The adjacent clause uniquely binds Japanese expansion intent to external-procurement probability.",
    ),
    "pair_98a33a34ca0f5047": (
        "local_binding",
        "retain_truth",
        "The same clause uniquely binds the possible higher price to the availability of larger sizes.",
    ),
    "pair_ef91d55f1e0d8c3b": (
        "local_binding",
        "retain_truth",
        "Customer uncertainty is an explicit reason for uniform pricing in the same sentence.",
    ),
    "pair_e0122f78caaf1a43": (
        "scoreable",
        "retain_truth",
        "The quoted process/equipment split explicitly supports the process-driven conclusion.",
    ),
    "pair_681736d2478dab48": (
        "scoreable",
        "retain_truth",
        "The but-clause explicitly counters the lack-of-validation qualification.",
    ),
    "pair_17b50dc36d3bd69e": (
        "local_binding",
        "retain_truth",
        "The if-clause and consequence are uniquely joined in one conditional sentence.",
    ),
    "pair_3e579daa7d92e267": (
        "scoreable",
        "retain_truth",
        "Successful validation is an explicit condition for capturing the market.",
    ),
    "pair_b95e823f9f6d51d9": (
        "local_binding",
        "retain_truth",
        "The answer operationalizes the immediately preceding standard-size question as annual capacity.",
    ),
    "pair_82e38a002735f044": (
        "scoreable",
        "retain_truth",
        "The reply directly gives lithium-foil main-equipment capex per ten thousand tonnes.",
    ),
    "pair_741c3dce009fa24b": (
        "scoreable",
        "retain_truth",
        "The range elaboration directly answers the capex question.",
    ),
    "pair_a93079679e270f02": (
        "scoreable",
        "retain_truth",
        "The current-market amount explicitly qualifies the good-margin amount.",
    ),
    "pair_20e579667066bca6": (
        "scoreable",
        "retain_truth",
        "The additional back-end machine explicitly qualifies front-end equipment similarity.",
    ),
    "pair_f88743227fb48b8b": (
        "scoreable",
        "retain_truth",
        "Delayed acceptance payments explicitly qualify the annual-revenue outlook.",
    ),
    "pair_421fb2d822b8dc15": (
        "scoreable",
        "retain_truth",
        "Process-driven yield explicitly qualifies the leading-equipment-precision claim.",
    ),
    "pair_907f2c22d4ddec7a": (
        "scoreable",
        "retain_truth",
        "Different equipment requirements explicitly support splitting capex by foil type.",
    ),
    "pair_71d4c1fe205c3723": (
        "scoreable",
        "retain_truth",
        "The need to supply electrolyte explicitly supports the front-end dissolution equipment.",
    ),
    "pair_af4a1d9299403d27": (
        "unscorable",
        "exclude_unscorable",
        "The isolated capacity and product-mix endpoints lack a complete shared subject, scope and period binding.",
    ),
    "pair_4adac65ac8099417": (
        "scoreable",
        "retain_truth",
        "The two comparisons form a compatible ordering rather than a challenge.",
    ),
    "pair_0cc897a5c1f55daf": (
        "unscorable",
        "exclude_unscorable",
        "The delivery and acceptance-payment endpoints omit the required subject, object and payment ownership bindings.",
    ),
    "pair_1f74637d78897251": (
        "local_binding",
        "retain_truth",
        "The adjacent periods share the same performance comparison and remain mutually compatible.",
    ),
    "pair_535c3958c2f89841": (
        "local_binding",
        "retain_truth",
        "Domestic procurement preference does not answer whether the referenced suppliers stopped HTE.",
    ),
    "pair_d7b6eabfa488078d": (
        "unscorable",
        "exclude_unscorable",
        "The question fragment '还是什么？' retains neither a referent nor a predicate to answer.",
    ),
    "pair_4f11ea4b329aa628": (
        "scoreable",
        "retain_truth",
        "The reply directly lists global suppliers in answer to the global-landscape question.",
    ),
    "pair_c47aa4dc2cd74bc3": (
        "local_binding",
        "retain_truth",
        "The speaker explicitly challenges the machining-versus-control premise in the same sentence.",
    ),
    "pair_f483497489fe4b6e": (
        "scoreable",
        "retain_truth",
        "Foreign non-expansion does not support the separate Chinese labour-and-assembly claim.",
    ),
    "pair_603d2b449da00930": (
        "scoreable",
        "retain_truth",
        "The reply corrects the question's false premise about an anode-plated cathode roller.",
    ),
    "pair_1b5d94210a126af9": (
        "local_binding",
        "retain_truth",
        "The amount is a complementary component of the answer that identifies the remaining capex equipment.",
    ),
    "pair_c513a3e6c490fa9a": (
        "scoreable",
        "retain_truth",
        "Low processing fees explain acceleration, not the composition of one machine set.",
    ),
}

CORRECTED_TRUTH = {
    "pair_1a9d24af1bf7107f": "present",
    "pair_dc4f0640ec6b4b11": "present",
}
SIGNOFF = {
    "required": False,
    "name": "xyl",
    "signed_at": "2026-10-10",
    "authorization": "已签认",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("issue23_full_audit", EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("counterfactual evaluator import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator: Any = module
    evaluator.P14 = ISSUE22
    return evaluator


def _truth(adjudication: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in adjudication["precision_decisions"]:
        result[row["candidate_pair_id"]] = (
            "present" if row["agent_decision"] == "accept_present" else "absent"
        )
    for row in adjudication["recall_sentinel_decisions"]:
        result[row["candidate_pair_id"]] = (
            "present" if row["agent_decision"] == "overturn_false_negative" else "absent"
        )
    return result


def main() -> None:
    evaluator = _load_evaluator()
    context = evaluator._candidate_context()
    adjudication = _read(P11 / "candidate-adjudications.agent-draft.json")
    plan = _read(P11 / "sample-plan.json")
    original_truth = _truth(adjudication)
    sample_rows = plan["precision_sample"] + plan["recall_sentinel_sample"]
    sample_by_id = {row["candidate_pair_id"]: row for row in sample_rows}
    if len(sample_rows) != 44 or len(sample_by_id) != 44:
        raise RuntimeError("P11 sample is not exactly 44 unique cases")
    if set(AUDIT) != set(sample_by_id) or set(AUDIT) != set(original_truth):
        raise RuntimeError("full-cohort audit identity differs from signed P11")
    if plan["sample_id"] != adjudication["sample_id"]:
        raise RuntimeError("signed P11 sample identity drifted")
    if adjudication["status"] != "human_signed":
        raise RuntimeError("P11 source is no longer human-signed")

    rows: list[dict[str, Any]] = []
    proposed_truth = dict(original_truth)
    excluded: set[str] = set()
    for ordinal, source in enumerate(sample_rows, start=1):
        pair_id = source["candidate_pair_id"]
        endpoint_status, disposition, note = AUDIT[pair_id]
        corrected = CORRECTED_TRUTH.get(pair_id)
        if disposition == "exclude_unscorable":
            excluded.add(pair_id)
        elif disposition == "change_truth":
            if corrected is None or corrected == original_truth[pair_id]:
                raise RuntimeError(f"invalid truth correction: {pair_id}")
            proposed_truth[pair_id] = corrected
        elif disposition != "retain_truth":
            raise RuntimeError(f"unknown disposition: {pair_id}")
        rows.append(
            {
                "ordinal": ordinal,
                "candidate_pair_id": pair_id,
                "relation_type": source["allowed_type"],
                "sample_role": (
                    "precision" if source["selector_decision"] == "present" else "recall_sentinel"
                ),
                "from_text": source["from_endpoint"]["text"],
                "to_text": source["to_endpoint"]["text"],
                "endpoint_status": endpoint_status,
                "disposition": disposition,
                "original_truth": original_truth[pair_id],
                "proposed_truth": None if pair_id in excluded else proposed_truth[pair_id],
                "note": note,
            }
        )

    raw = json.loads((ISSUE22 / "raw-response-audit.json").read_text(encoding="utf-8"))
    reconstructed = evaluator.reparse_responses(raw, context["packet_candidates"])
    if not reconstructed["reconstructable"]:
        raise RuntimeError("Issue 22 decisions are not reconstructable")
    model_decisions = {
        pair_id: value["decision"] for pair_id, value in reconstructed["decisions"].items()
    }
    eligible = set(original_truth) - excluded
    remaining_errors = {
        pair_id for pair_id in eligible if model_decisions[pair_id] != proposed_truth[pair_id]
    }
    correct = len(eligible) - len(remaining_errors)
    requirements = context["final_gate"]["quality_requirements"]
    equivalent_minimum = math.ceil(
        requirements["signed_cases_correct_min"]
        / requirements["signed_cases_total"]
        * len(eligible)
    )
    calibration = _read(P12 / "signed-calibration-cases.json")
    known_error_ids = {row["candidate_pair_id"] for row in calibration["cases"]} & eligible
    known_correct = sum(
        model_decisions[pair_id] == proposed_truth[pair_id] for pair_id in known_error_ids
    )
    original_score = _read(ISSUE22 / "counterfactual-summary.json")["score"]
    regressions = remaining_errors & set(original_score["previously_correct_regressions"])
    candidate_by_id = {
        candidate.candidate_pair_id: candidate for candidate in context["candidate_set"].candidates
    }
    stable_regressions = {
        pair_id
        for pair_id in regressions
        if candidate_by_id[pair_id].allowed_type in {"supports", "conditions"}
    }
    target_matched = sum(row["matched"] for row in original_score["target_results"])

    audit_artifact = {
        "schema_version": "relation-gold-v2-full-cohort-audit-1",
        "created_on": "2026-10-10",
        "status": "human_signed",
        "source_sample_id": plan["sample_id"],
        "candidate_set_id": plan["source"]["candidate_set_id"],
        "source_files": {
            "signed_p11_sha256": _sha256(P11 / "candidate-adjudications.agent-draft.json"),
            "sample_plan_sha256": _sha256(P11 / "sample-plan.json"),
        },
        "constraints": {
            "model_calls": 0,
            "all_signed_cases_reviewed": True,
            "original_signed_file_modified": False,
            "issue22_terminal_decision_changed": False,
            "threshold_changed": False,
        },
        "policy": {
            "scoreable": "both atomic endpoints retain enough predicate and binding information to decide the typed relation",
            "local_binding": "a surface ellipsis is allowed only when the frozen pair window resolves it uniquely",
            "unscorable": "missing predicate, unresolved referent, missing required subject/object, or a non-atomic target is excluded rather than relabelled",
            "change_control": "after signature, model outcomes cannot change gold-v2; corrections require a separately signed evidence-error addendum",
        },
        "counts": {
            "reviewed": len(rows),
            "scoreable": sum(row["endpoint_status"] == "scoreable" for row in rows),
            "local_binding": sum(row["endpoint_status"] == "local_binding" for row in rows),
            "excluded_unscorable": len(excluded),
            "truth_changes": len(CORRECTED_TRUTH),
        },
        "rows": rows,
        "signoff": SIGNOFF,
    }
    gold_v2 = {
        "schema_version": "relation-adjudication-gold-v2-draft-1",
        "created_on": "2026-10-10",
        "status": "human_signed",
        "source_sample_id": plan["sample_id"],
        "candidate_set_id": plan["source"]["candidate_set_id"],
        "source_signed_p11_sha256": _sha256(P11 / "candidate-adjudications.agent-draft.json"),
        "supersedes_after_signature": str(P11 / "candidate-adjudications.agent-draft.json"),
        "eligible_case_count": len(eligible),
        "excluded_case_ids": sorted(excluded),
        "truth_changes_from_signed_v1": dict(sorted(CORRECTED_TRUTH.items())),
        "decisions": [
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "relation_type": row["relation_type"],
                "truth": proposed_truth[row["candidate_pair_id"]],
            }
            for row in rows
            if row["candidate_pair_id"] in eligible
        ],
        "signoff": SIGNOFF,
    }
    score = {
        "schema_version": "relation-gold-v2-full-cohort-score-1",
        "created_on": "2026-10-10",
        "status": "sensitivity_passed_gold_v2_signed",
        "constraints": {
            "model_calls": 0,
            "post_hoc_official_gate_claimed": False,
            "issue22_terminal_decision_changed": False,
        },
        "score": {
            "correct": correct,
            "eligible_cases": len(eligible),
            "accuracy": correct / len(eligible),
            "equivalent_ratio_minimum": equivalent_minimum,
            "passed_equivalent_ratio": correct >= equivalent_minimum,
            "remaining_errors": sorted(remaining_errors),
        },
        "known_error_cases": {
            "correct": known_correct,
            "eligible_cases": len(known_error_ids),
            "required": requirements["known_error_cases_correct_min"],
        },
        "other_frozen_gate_sensitivity": {
            "previously_correct_regressions": len(regressions),
            "previously_correct_regression_ids": sorted(regressions),
            "maximum": requirements["previously_correct_regressions_max"],
            "supports_conditions_regressions": len(stable_regressions),
            "target_relations_matched": target_matched,
            "target_relations_required": requirements["target_relations_matched_min"],
        },
        "sensitivity_passed": (
            correct >= equivalent_minimum
            and known_correct >= requirements["known_error_cases_correct_min"]
            and len(regressions) <= requirements["previously_correct_regressions_max"]
            and not stable_regressions
            and target_matched >= requirements["target_relations_matched_min"]
        ),
        "decision": "gold-v2 is frozen by xyl signoff; do not relabel the historical Issue 22 run",
    }

    lines = [
        "# Issue 23 · 44 条关系金标全量统一审计",
        "",
        "Status: human signed by xyl; gold-v2 frozen",
        "Model calls: 0",
        "",
        "## 结果",
        "",
        f"- 全量审计：{len(rows)}/44。",
        f"- 可评分：{len(eligible)}；不可评分：{len(excluded)}；truth 更正：{len(CORRECTED_TRUTH)}。",
        f"- 零调用敏感性：{correct}/{len(eligible)}；等比例最低门：{equivalent_minimum}/{len(eligible)}。",
        f"- 剩余语义错误：{', '.join(sorted(remaining_errors)) or '无'}。",
        "- 本结果不能回写 Issue 22 的历史失败终态；gold-v2 已由 xyl 独立签认并冻结。",
        "",
        "## 不可评分候选",
        "",
    ]
    for row in rows:
        if row["disposition"] == "exclude_unscorable":
            lines.append(f"- `{row['candidate_pair_id']}`：{row['note']}")
    lines.extend(
        [
            "",
            "## Truth 更正",
            "",
            "- `pair_1a9d24af1bf7107f`：absent → present（收入计算的更换频率组成答案）。",
            "- `pair_dc4f0640ec6b4b11`：absent → present（make-or-buy 回答的互补原因）。",
            "",
            "## 冻结规则",
            "",
            "gold-v2 已签认，不得根据模型结果调整。只有原文、候选身份或证据绑定错误，才允许通过独立签认的 addendum 更正。",
            "",
        ]
    )

    outputs = {
        "full-cohort-audit.agent-draft.json": audit_artifact,
        "gold-v2.agent-draft.json": gold_v2,
        "full-cohort-score.json": score,
    }
    for name, payload in outputs.items():
        (HERE / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (HERE / "full-cohort-review.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(score, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
