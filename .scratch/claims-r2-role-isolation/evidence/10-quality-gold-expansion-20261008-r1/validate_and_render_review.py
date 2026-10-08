from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_ROLES = {"claims", "material_items", "material_relations"}
ALLOWED_RELATIONS = {
    "supports",
    "challenges",
    "conditions",
    "invalidates",
    "answers",
    "motivates",
    "attributes",
    "elaborates",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(review: dict[str, Any], source_export: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    records = review.get("records", [])
    if review.get("status") != "draft_pending_human_review":
        errors.append("review_status_must_remain_draft")
    if review.get("reviewer") is not None or review.get("adjudicator") is not None:
        errors.append("draft_must_not_claim_human_signoff")
    if review.get("candidate_outputs_observed_before_draft") is not False:
        errors.append("candidate_outputs_must_not_be_observed_before_draft")
    if review.get("table_content_included") is not False:
        errors.append("table_content_must_be_excluded")
    if review.get("holdout_accessed") is not False:
        errors.append("holdout_must_not_be_accessed")

    units: dict[tuple[str, str], str] = {}
    source_ids: set[str] = set()
    for source in source_export.get("sources", []):
        source_id = f"sha256:{source['source_sha256']}"
        source_ids.add(source_id)
        if source.get("issues"):
            errors.append(f"reader_issues:{source_id}")
        for unit in source.get("units", []):
            if unit.get("kind") in {"table", "table_row"}:
                errors.append(f"table_unit_exported:{source_id}:{unit.get('locator')}")
            units[(source_id, unit["locator"])] = unit["text"]

    ids: set[str] = set()
    identities: set[tuple[object, ...]] = set()
    item_ids: set[str] = set()
    counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    risk_or_condition = 0
    for record in records:
        record_id = record.get("record_id")
        role = record.get("role")
        source_id = record.get("source_id")
        locator = record.get("locator")
        quote = record.get("quote")
        semantic_fields = record.get("semantic_fields")
        if not isinstance(record_id, str) or not record_id or record_id in ids:
            errors.append(f"duplicate_or_invalid_record_id:{record_id}")
            continue
        ids.add(record_id)
        if role not in ALLOWED_ROLES:
            errors.append(f"invalid_role:{record_id}:{role}")
            continue
        counts[role] += 1
        source_counts[source_id] += 1
        if role == "material_items":
            item_ids.add(record_id)
        if source_id not in source_ids:
            errors.append(f"unapproved_source:{record_id}:{source_id}")
        if record.get("origin") != "llm_prose":
            errors.append(f"non_prose_origin:{record_id}")
        if record.get("review_status") != "pending":
            errors.append(f"record_not_pending:{record_id}")
        if (
            not isinstance(semantic_fields, dict)
            or not semantic_fields
            or not all(
                isinstance(key, str) and isinstance(value, str) and key and value
                for key, value in semantic_fields.items()
            )
        ):
            errors.append(f"invalid_semantic_fields:{record_id}")
        else:
            identity = (
                role,
                source_id,
                record.get("origin"),
                tuple(sorted(semantic_fields.items())),
            )
            if identity in identities:
                errors.append(f"duplicate_semantic_identity:{record_id}")
            identities.add(identity)
        if record.get("risk_or_condition") is True:
            risk_or_condition += 1
        if not isinstance(locator, str) or not isinstance(quote, str) or not quote:
            errors.append(f"missing_locator_or_quote:{record_id}")
            continue
        locators = locator.split(" + ")
        referenced = [units.get((source_id, value)) for value in locators]
        if any(text is None for text in referenced):
            errors.append(f"unknown_locator:{record_id}:{locator}")
            continue
        if len(referenced) == 1:
            referenced_text = referenced[0]
            if referenced_text is None or quote not in referenced_text:
                errors.append(f"quote_mismatch:{record_id}")
        else:
            for fragment in quote.split("；"):
                if not any(fragment in text for text in referenced if text is not None):
                    errors.append(f"compound_quote_mismatch:{record_id}:{fragment}")

    for role in ALLOWED_ROLES:
        if counts[role] < 20:
            errors.append(f"insufficient_draft_records:{role}:{counts[role]}/20")
    if risk_or_condition < 20:
        errors.append(f"insufficient_risk_or_condition:{risk_or_condition}/20")
    for record in records:
        if record.get("role") != "material_relations":
            continue
        fields = record.get("semantic_fields", {})
        from_id = fields.get("from_gold_record_id")
        to_id = fields.get("to_gold_record_id")
        if from_id not in item_ids or to_id not in item_ids:
            errors.append(f"relation_endpoint_missing:{record['record_id']}")
        if fields.get("relation") not in ALLOWED_RELATIONS:
            errors.append(f"invalid_relation_type:{record['record_id']}")
        if fields.get("provenance") not in {"source_explicit", "system_inferred"}:
            errors.append(f"invalid_relation_provenance:{record['record_id']}")
        by_id = {item["record_id"]: item for item in records}
        if from_id in by_id and by_id[from_id]["source_id"] != record["source_id"]:
            errors.append(f"relation_from_source_mismatch:{record['record_id']}")
        if to_id in by_id and by_id[to_id]["source_id"] != record["source_id"]:
            errors.append(f"relation_to_source_mismatch:{record['record_id']}")

    return {
        "schema_version": "corpus-structured-non-table-gold-review-validation-v1",
        "status": "valid_draft" if not errors else "invalid_draft",
        "errors": errors,
        "counts": dict(sorted(counts.items())),
        "source_record_counts": dict(sorted(source_counts.items())),
        "risk_or_condition_records": risk_or_condition,
        "minimum_20_per_role_satisfied": all(counts[role] >= 20 for role in ALLOWED_ROLES),
        "human_signoff_complete": False,
        "formal_gold_frozen": False,
    }


def render(review: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "# 非表格真实开发金标人工审阅",
        "",
        "日期：2026-10-08  ",
        "状态：待人工逐条确认；不是冻结金标",
        "",
        "本审阅包只使用两份已批准开发材料的正文单元，表格全部排除，未访问留出，也尚未运行本专项候选。",
        "只有审核人对每条记录作出接受/修改/拒绝终态，并另行生成不可变 freeze 后，才可写入正式质量分母。",
        "",
        "## 数量",
        "",
        f"- Claims：{validation['counts'].get('claims', 0)}",
        f"- material_items：{validation['counts'].get('material_items', 0)}",
        f"- material_relations：{validation['counts'].get('material_relations', 0)}",
        f"- 风险/条件记录：{validation['risk_or_condition_records']}",
        f"- 机械校验：{validation['status']}",
        "",
        "## 审核方式",
        "",
        "逐条核对引用、主体/期间/单位、事实或预测、观点归属、条件方向和关系方向。请在 JSON 中将",
        "`review_status` 改为 `accepted`、`edited` 或 `rejected`；编辑时保留原值和裁定理由。不要直接修改",
        "旧冻结包。全部完成后，在文末填写审核人、裁定人和日期，再生成新 freeze。",
    ]
    role_titles = {
        "claims": "Claims",
        "material_items": "Material items",
        "material_relations": "Material relations",
    }
    for role, title in role_titles.items():
        lines.extend(("", f"## {title}", ""))
        for record in review["records"]:
            if record["role"] != role:
                continue
            fields = "；".join(f"{key}={value}" for key, value in record["semantic_fields"].items())
            lines.extend(
                (
                    f"### [ ] {record['record_id']}",
                    "",
                    f"- 来源：`{record['source_id']}`",
                    f"- 定位：`{record['locator']}`",
                    f"- 原文：{record['quote']}",
                    f"- 语义：{fields}",
                    f"- 关键项：{str(record['critical']).lower()}；风险/条件：{str(record['risk_or_condition']).lower()}",
                    "- 人工裁定：pending",
                    "",
                )
            )
    lines.extend(
        (
            "## 人工签认（全部逐条裁定后填写）",
            "",
            "- 审核人：",
            "- 争议裁定人：",
            "- 签认日期：",
            "- 是否确认本包在候选运行前完成：",
            "- 是否确认未包含表格及留出：",
            "",
        )
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--source-export", type=Path, required=True)
    parser.add_argument("--validation-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    args = parser.parse_args()
    review = _load(args.review)
    source_export = _load(args.source_export)
    validation = validate(review, source_export)
    validation["inputs"] = {
        str(args.review): f"sha256:{_sha256(args.review)}",
        str(args.source_export): f"sha256:{_sha256(args.source_export)}",
    }
    args.validation_out.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_out.write_text(render(review, validation), encoding="utf-8")
    if validation["errors"]:
        raise SystemExit("review draft validation failed")


if __name__ == "__main__":
    main()
