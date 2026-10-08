"""Validate and render an explicitly scoped, human-reviewable gold draft.

This checks evidence and declared normalization, not arbitrary semantic entailment.
It performs no model calls, database access or discovery of additional sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ROLES = ("claims", "material_items", "material_relations")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_value(basis: dict[str, Any]) -> str:
    if basis["kind"] == "categorical":
        if basis["token"] != "实现批量供应" or basis["normalized"] != "batch_supply":
            raise ValueError("unsupported categorical normalization")
        return "batch_supply"
    token = basis["token"]
    if not re.fullmatch(r"\d+(?:\.\d+)?万?(?:(?:到|至)\d+(?:\.\d+)?万?)?", token):
        raise ValueError("unsupported numeric token")
    expected_scale = Decimal(10000 if "万" in token else 1)
    if Decimal(basis["scale"]) != expected_scale:
        raise ValueError("scale contradicts quoted number")
    values = [Decimal(value) * expected_scale for value in re.findall(r"\d+(?:\.\d+)?", token)]
    if len(values) == 2 and values[0] > values[1]:
        raise ValueError("reversed interval")
    return "-".join(format(value.normalize(), "f") for value in values)


def normalized_period(basis: dict[str, Any], context: str) -> str:
    if basis["kind"] == "descriptive":
        if basis != {"kind": "descriptive", "token": "比较早期", "normalized": "early_stage"}:
            raise ValueError("unsupported descriptive period")
        if basis["token"] not in context:
            raise ValueError("missing descriptive period evidence")
        return "early_stage"
    token = basis["year_token"]
    if token not in context:
        raise ValueError("year token missing from context")
    match = re.fullmatch(r"(\d{4}|\d{2})(?:年)?", token)
    if match is None:
        raise ValueError("unsupported year token")
    year = int(match[1])
    if year < 100:
        year += 2000
    suffix = basis["suffix"]
    cues = {"H1": ("中报", "H1"), "H2": ("下半年", "H2"), "Q2": ("Q2",), "Q3": ("三季度",)}
    if suffix in cues:
        if not any(cue in context for cue in cues[suffix]):
            raise ValueError("period qualifier lacks evidence")
    elif suffix and (suffix != "-08-28" or f"{year}{suffix}" not in context):
        raise ValueError("unsupported or ungrounded date suffix")
    return f"{year}{suffix}"


def check_condition(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    condition = record["semantic_fields"].get("condition", "")
    rid = record["record_id"]
    logic = record["condition_logic"]

    def visit(node: dict[str, Any]) -> None:
        for field in ("value", "baseline", "lower", "upper"):
            if field in node and str(node[field]).lstrip("-") not in condition:
                errors.append(f"condition_threshold_missing:{rid}:{field}")
        if (
            node["op"] == "compare"
            and not logic.get("args")
            and node["comparator"] not in condition
        ):
            errors.append(f"condition_operator_missing:{rid}")
        if node["op"] == "all" and " AND " not in condition:
            errors.append(f"condition_conjunction_missing:{rid}")
        if (
            node.get("inner_operator") == "unknown"
            and "condition_inner_boolean" not in record["unknown_fields"]
        ):
            errors.append(f"condition_ambiguity_lost:{rid}")
        for child in node.get("args", []):
            visit(child)

    visit(logic)
    return errors


def validate(
    review: dict[str, Any], contract: dict[str, Any], sources: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    if review.get("evaluation_scope") != "selected_target_recall_not_exhaustive_document_gold":
        errors.append("scope_must_remain_selected_targets")
    for key in (
        "candidate_outputs_observed_before_draft",
        "table_content_included",
        "holdout_accessed",
    ):
        if review.get(key) is not False:
            errors.append(f"invalid_boundary:{key}")
    if review.get("status") != "draft_pending_human_review":
        errors.append("this_validator_cannot_freeze_gold")
    units = {}
    for source in sources["sources"]:
        sid = f"sha256:{source['source_sha256']}"
        if source["issues"]:
            errors.append(f"reader_issues:{sid}")
        for unit in source["units"]:
            units[(sid, unit["locator"])] = unit
    expected_sources = {f"sha256:{s['source_sha256']}" for s in sources["sources"]}
    if {s["source_id"] for s in review["sources"]} != expected_sources:
        errors.append("source_membership_mismatch")
    scope = {
        (s["source_id"], loc) for s in contract["candidate_input_scope"] for loc in s["locators"]
    }

    def check_evidence(e: dict[str, Any], sid: str, rid: str) -> None:
        key = (e.get("source_id"), e.get("locator"))
        u = units.get(key)
        if e.get("source_id") != sid or u is None or key not in scope:
            errors.append(f"unscoped_evidence:{rid}")
            return
        if u["kind"] in {"table", "table_row"}:
            errors.append(f"table_evidence:{rid}")
        if e.get("offset_basis") != "unit_codepoints":
            errors.append(f"invalid_offset_basis:{rid}")
        start, end = e.get("start"), e.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not (0 <= start < end <= len(u["text"]))
        ):
            errors.append(f"invalid_offsets:{rid}")
        elif u["text"][start:end] != e.get("quote"):
            errors.append(f"quote_mismatch:{rid}")
        digest = hashlib.sha256(u["text"].encode()).hexdigest()
        if e.get("unit_text_sha256") != digest or u["text_sha256"] != digest:
            errors.append(f"unit_hash_mismatch:{rid}")

    records = review["records"]
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        errors.append("duplicate_record_id")
    speaker_ids = {s["speaker_id"] for s in review["speakers"]}
    behavior_keys: set[tuple[str, ...]] = set()
    counts: Counter[str] = Counter()
    accepted: Counter[str] = Counter()
    identities: set[str] = set()
    for r in records:
        rid, role, f = r["record_id"], r["role"], r["semantic_fields"]
        if role not in ROLES:
            errors.append(f"unknown_role:{rid}")
            continue
        if r["source_id"] not in expected_sources or r.get("origin") != "llm_prose":
            errors.append(f"invalid_source_or_origin:{rid}")
        if r["review_status"] not in contract["record_states"]:
            errors.append(f"invalid_review_status:{rid}")
        if r["review_status"] != "rejected":
            counts[role] += 1
        if r["review_status"] in {"accepted", "edited"}:
            accepted[role] += 1
        if r["review_status"] != "pending":
            a = r.get("adjudication", {})
            if (
                not a.get("reviewer")
                or not a.get("reason")
                or a.get("decision") != r["review_status"]
            ):
                errors.append(f"missing_human_adjudication:{rid}")
            if r["review_status"] == "edited" and not a.get("changes"):
                errors.append(f"missing_edit_history:{rid}")
        if not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in f.items()):
            errors.append(f"invalid_semantic_fields:{rid}")
        if not set(contract["role_required_fields"][role]).issubset(f):
            errors.append(f"missing_fields:{rid}")
            continue
        identity = json.dumps([role, r["source_id"], f], sort_keys=True, ensure_ascii=False)
        if identity in identities:
            errors.append(f"duplicate_identity:{rid}")
        identities.add(identity)
        if not r.get("evidence") or not r.get("context_evidence"):
            errors.append(f"missing_evidence:{rid}")
            continue
        if r["quote"] != r["evidence"][0]["quote"] or r["locator"] != r["evidence"][0]["locator"]:
            errors.append(f"legacy_evidence_mismatch:{rid}")
        for e in r["evidence"] + r["context_evidence"]:
            check_evidence(e, r["source_id"], rid)
        context = "\n".join(e["quote"] for e in r["context_evidence"])
        if r["critical"] and not r.get("critical_reason"):
            errors.append(f"unexplained_critical:{rid}")
        if r["risk_or_condition"] and not r.get("risk_reason"):
            errors.append(f"unexplained_risk:{rid}")
        if role == "claims":
            if contract["metric_units"].get(f["metric"]) != f["unit"]:
                errors.append(f"invalid_metric_unit:{rid}")
            if (
                f["factuality"] not in {"actual", "forecast"}
                or f["perspective"] not in contract["perspectives"]
            ):
                errors.append(f"invalid_claim_enum:{rid}")
            try:
                basis = r["value_normalization"]
                if basis["token"] not in context or normalized_value(basis) != f["value"]:
                    errors.append(f"value_normalization_mismatch:{rid}")
                if normalized_period(r["period_normalization"], context) != f["period"]:
                    errors.append(f"period_normalization_mismatch:{rid}")
            except (KeyError, ValueError, ArithmeticError) as exc:
                errors.append(f"invalid_normalization:{rid}:{exc}")
        elif role == "material_items":
            for key, allowed in (
                ("semantic_type", contract["semantic_types"]),
                ("statement_role", contract["statement_roles"]),
                ("perspective", contract["perspectives"]),
                ("polarity", ["affirmed", "negated", "mixed", "unknown"]),
            ):
                if f[key] not in allowed:
                    errors.append(f"invalid_enum:{rid}:{key}")
            if f["speaker_ref"] not in speaker_ids:
                errors.append(f"unknown_speaker:{rid}")
            if f["semantic_type"] == "behavior":
                if f.get("behavior_status") != "intent":
                    errors.append(f"behavior_intent_required:{rid}")
                key = (r["source_id"], r["locator"], r["quote"], f["speaker_ref"])
                if key in behavior_keys:
                    errors.append(f"duplicate_behavior_evidence:{rid}")
                behavior_keys.add(key)
            logic = r.get("condition_logic")
            if logic:
                errors.extend(check_condition(r))
        else:
            if f["provenance"] != "source_explicit":
                errors.append(f"inferred_relation_forbidden:{rid}")
            if f["relation"] not in contract["relation_types"]:
                errors.append(f"invalid_relation:{rid}")
            for key in ("from_gold_record_id", "to_gold_record_id"):
                end = by_id.get(f[key])
                if (
                    not end
                    or end["role"] != "material_items"
                    or end["source_id"] != r["source_id"]
                    or end["review_status"] == "rejected"
                ):
                    errors.append(f"invalid_relation_endpoint:{rid}:{key}")
            if f["from_gold_record_id"] == f["to_gold_record_id"]:
                errors.append(f"self_relation:{rid}")
    relation_pairs = {
        (
            r["semantic_fields"]["from_gold_record_id"],
            r["semantic_fields"]["to_gold_record_id"],
            r["semantic_fields"]["relation"],
        )
        for r in records
        if r["role"] == "material_relations" and r["review_status"] != "rejected"
    }
    for group in review["condition_groups"]:
        target = by_id.get(group["target_record_id"])
        if not target or target["review_status"] == "rejected":
            errors.append(f"missing_condition_target:{group['group_id']}")
            continue
        check_evidence(group["evidence"], target["source_id"], group["group_id"])
        if group["operator"] != "any":
            errors.append(f"condition_group_operator:{group['group_id']}")
        for cid in group["condition_record_ids"]:
            if (cid, target["record_id"], "conditions") not in relation_pairs:
                errors.append(f"missing_condition_edge:{cid}")
    # Pack-specific regression assertions tie high-risk readings to explicit review criteria.
    for rid, expected in contract.get("review_assertions", {}).items():
        r = by_id.get(rid)
        if r is None:
            errors.append(f"missing_review_target:{rid}")
            continue
        for field, value in expected.items():
            actual = (
                r.get(field)
                if field in {"condition_logic", "unknown_fields"}
                else r["semantic_fields"].get(field)
            )
            if actual != value:
                errors.append(f"review_assertion_mismatch:{rid}:{field}")
    for role in ROLES:
        if counts[role] < contract["minimum_accepted_records_per_role"]:
            errors.append(f"insufficient_draft_records:{role}")
    return {
        "status": "valid_review_draft" if not errors else "invalid_review_draft",
        "errors": errors,
        "draft_counts": dict(counts),
        "human_accepted_counts": dict(accepted),
        "risk_record_counts_by_role": {
            role: sum(
                r["risk_or_condition"]
                for r in records
                if r["role"] == role and r["review_status"] != "rejected"
            )
            for role in ROLES
        },
        "independent_risk_scenario_count": None,
        "mechanical_checks_prove_semantic_correctness": False,
        "formal_gold_frozen": False,
        "quality_gate_passed": False,
        "scope": review["evaluation_scope"],
        "unresolved_semantic_ambiguities": [
            {"record_id": r["record_id"], "fields": r["unknown_fields"]}
            for r in records
            if r["unknown_fields"]
        ],
    }


def candidate_precision(
    decisions: list[dict[str, Any]], *, expected_candidate_ids: set[str]
) -> dict[str, Any]:
    """Tally an explicitly adjudicated candidate ledger, never infer FP from gold absence."""
    counts: Counter[str] = Counter()
    seen_ids: set[tuple[str, str]] = set()
    matched: set[tuple[str, str]] = set()
    slices = {(d["stage"], d["role"]) for d in decisions}
    if len(slices) > 1:
        raise ValueError("score raw/validated and each role separately")
    if {d["candidate_id"] for d in decisions} != expected_candidate_ids:
        raise ValueError("adjudication must cover the full candidate roster")
    for decision in decisions:
        identity = (decision["stage"], decision["candidate_id"])
        if identity in seen_ids:
            raise ValueError("duplicate candidate adjudication")
        seen_ids.add(identity)
        judgement = decision["judgement"]
        if judgement not in {
            "matched",
            "correct_extra",
            "incorrect",
            "duplicate",
            "unresolved",
            "out_of_scope",
        }:
            raise ValueError("unknown candidate judgement")
        if judgement != "unresolved" and (
            not decision.get("reviewer")
            or not decision.get("reason")
            or not decision.get("original_candidate")
            or not decision.get("evidence")
        ):
            raise ValueError("adjudication requires named reviewer and reason")
        if judgement == "matched":
            gold_id = decision.get("matched_gold_id")
            if not gold_id:
                raise ValueError("matched candidate needs gold target")
            target = (decision["stage"], gold_id)
            if target in matched:
                raise ValueError("second match must be explicitly classified duplicate")
            matched.add(target)
        counts[judgement] += 1
    denominator = sum(counts[k] for k in ("matched", "correct_extra", "incorrect", "duplicate"))
    precision = (
        None
        if counts["unresolved"] or not denominator
        else f"{counts['matched'] + counts['correct_extra']}/{denominator}"
    )
    return {"counts": dict(counts), "precision": precision, "quality_gate_passed": False}


def render(review: dict[str, Any], report: dict[str, Any]) -> str:
    sources = {s["source_id"]: s["path"] for s in review["sources"]}
    by_id = {r["record_id"]: r for r in review["records"]}
    lines = [
        "# 非表格真实开发金标审阅 r2",
        "",
        "状态：待人工语义裁定；尚未冻结。",
        "",
        "本包评估指定目标的召回，并非两份材料的穷尽金标。额外正确输出须单独裁定，不自动计 FP。",
        "",
        "数量：" + json.dumps(report["draft_counts"], ensure_ascii=False),
        "",
        "风险/条件按角色计数："
        + json.dumps(report["risk_record_counts_by_role"], ensure_ascii=False),
        "",
        "这些记录存在关联，不代表独立风险场景数量。机械校验仅检查引文、字段和已声明规则，不能证明全部语义正确。",
        "",
        "逐条在 JSON 的 review_status/adjudication 中填写终态、审核人、理由；修改附 before/after/reason。Markdown 由 JSON 生成。",
        "",
        "I17 保留公司改口子项的原文歧义，不猜测内部 AND/OR。",
        "",
        "## 条件组合",
        "",
    ]
    for group in review["condition_groups"]:
        lines.append(
            f"- {group['group_id']}: ANY({', '.join(group['condition_record_ids'])}) → {group['target_record_id']}"
        )
    for role in ROLES:
        lines.extend(["", f"## {role}", ""])
        for r in review["records"]:
            if r["role"] != role:
                continue
            rid, f = r["record_id"], r["semantic_fields"]
            lines.extend(
                [
                    f"### {rid} · {r['review_status']}",
                    "",
                    f"来源：{sources[r['source_id']]}；定位：`{r['locator']}`",
                    "",
                    f"原文：{r['quote']}",
                    "",
                    "预期字段：" + "；".join(f"{k}={v}" for k, v in f.items()),
                    "",
                ]
            )
            if role == "material_relations":
                lines.extend(
                    [
                        "端点："
                        + by_id[f["from_gold_record_id"]]["semantic_fields"]["proposition"]
                        + " → "
                        + by_id[f["to_gold_record_id"]]["semantic_fields"]["proposition"],
                        "",
                    ]
                )
            if r.get("condition_logic"):
                lines.extend(
                    ["条件逻辑：`" + json.dumps(r["condition_logic"], ensure_ascii=False) + "`", ""]
                )
            if r.get("review_notes"):
                lines.extend(["裁定提示：" + r["review_notes"], ""])
            if r["unknown_fields"]:
                lines.extend(["明确未知：" + ", ".join(r["unknown_fields"]), ""])
            lines.extend(
                [
                    f"关键项：{r['critical']}；原因：{r['critical_reason'] or '无'}",
                    "",
                    "<details><summary>完整必要语境</summary>",
                    "",
                ]
            )
            for e in r["context_evidence"]:
                lines.extend([f"`{e['locator']}`：{e['quote']}", ""])
            lines.extend(["</details>", ""])
    lines.extend(["## 已退出必答分母的 r1 记录", ""])
    lines.extend(f"- {r['record_id']}：{r['reason']}" for r in review["retired_records"])
    lines.extend(
        [
            "",
            "## 人工签认",
            "",
            f"审核人：{review.get('reviewer') or '待填写'}",
            f"裁定人：{review.get('adjudicator') or '待填写'}",
            "",
            "签认对象包含 scoring-contract.json 的范围和匹配规则；签认后另建冻结包，本文件不自动冻结。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="read-only validation of generated artifacts"
    )
    args = parser.parse_args()
    review = read_json(HERE / "gold-review-candidates.json")
    contract = read_json(HERE / "scoring-contract.json")
    source_path = (HERE / contract["source_export"]).resolve()
    sources = read_json(source_path)
    report = validate(review, contract, sources)
    for source in review["sources"]:
        if "sha256:" + sha256(REPO / source["path"]) != source["source_id"]:
            report["errors"].append(f"source_bytes_changed:{source['path']}")
    report["status"] = "invalid_review_draft" if report["errors"] else "valid_review_draft"
    if report["errors"]:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))
    markdown = render(review, report)
    if args.check:
        if (HERE / "gold-review.md").read_text(encoding="utf-8") != markdown:
            raise SystemExit("markdown/json mismatch")
        if read_json(HERE / "validation-report.json") != report:
            raise SystemExit("validation report stale")
        manifest = read_json(HERE / "draft-manifest.json")
        for path, digest in manifest["inputs"].items():
            if sha256(REPO / path) != digest:
                raise SystemExit(f"manifest mismatch: {path}")
    else:
        (HERE / "gold-review.md").write_text(markdown, encoding="utf-8")
        (HERE / "validation-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        parent = (HERE / review["parent_review"]).parent
        paths = [
            *sorted(HERE.glob("*.py")),
            HERE / "README.md",
            HERE / "scoring-contract.json",
            HERE / "gold-review-candidates.json",
            HERE / "gold-review.md",
            HERE / "validation-report.json",
            *sorted(parent.glob("*")),
        ]
        manifest = {
            "schema_version": "non-table-gold-review-draft-manifest-v2",
            "parent": str(parent.relative_to(REPO)),
            "formal_gold_frozen": False,
            "status": "draft_pending_human_review",
            "counts": report["draft_counts"],
            "inputs": {str(p.relative_to(REPO)): sha256(p) for p in paths if p.is_file()},
            "approved_source_bytes": {
                s["path"]: sha256(REPO / s["path"]) for s in review["sources"]
            },
        }
        (HERE / "draft-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
