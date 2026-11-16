"""Compact manifest feedback; source coordinates and raw exceptions stay in receipts."""

from __future__ import annotations

import json
import re
from typing import Any


def fit_manifest_payload(body: str, cap: int) -> str | None:
    """Register only our known projected manifest protocol with the generic fitter."""
    from plugins.corpus.projection import NAVIGATION_VERSION, is_navigation_protocol

    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or not is_navigation_protocol(payload.get("protocol")):
        return None
    if len(body) <= cap:
        return body
    return json.dumps({"ok": False, "protocol": NAVIGATION_VERSION,
                       "error": "manifest_feedback_budget_exceeded"})

# Messages are constructed from known codes, never copied from resolver errors
# or Pydantic diagnostics (both may include complete records and local paths).
_ACTIONS = {
    "not_in_report": "从当前报告逐字复制 report_quote，修改报告后重新提交。",
    "no_evidence": "附上实际已读原文的 evidence_ref，或删除该结论。",
    "invalid_evidence": "使用工具返回的完整引用；不要改写引用或展开隐藏字段。",
    "incomplete_evidence": "使用工具返回的完整 evidence_ref 重新提交。",
    "source_unresolvable": "引用无法解析；重新查询并使用实际读到的有效引用，或移除结论。",
    "quote_not_found": "引文与权威原文不符；使用实际读到的 evidence_ref，不要改写引文。",
    "pending_delivery": "片段待消息边界确认；下一轮重新提交，无需重复 fetch。",
    "not_delivered": "证据尚未完整送达；补读缺失原文后重新提交。",
    "missing_dependencies": "补齐所声明用途的必要证据，或收窄、移除结论。",
    "verification_error": "校验基础设施故障；稍后重试，不代表证据缺失或校验通过。",
    "publication_invalid": "语义发布版本已失效；重新查询后提交有效记录引用。",
    "purpose_not_allowed": "改用记录许可的用途，或另选支持该用途的证据。",
    "quality_not_accepted": "证据质量未通过；更换合格证据或移除结论。",
}
_FIELD_PATH = re.compile(
    r"conclusions\[\d+\](?:\.(?:evidence|semantic_references)\[\d+\])?"
    r"(?:\.(?:evidence_ref|purpose|required_dependencies|id))?"
)


def _schema_problem(message: str) -> dict[str, Any]:
    code, action = "invalid_submission", "按工具 schema 修正结论、引用及用途后重新提交。"
    if "evidence_ref" in message:
        code, action = "invalid_evidence", _ACTIONS["invalid_evidence"]
    elif "语义" in message or "semantic_references" in message:
        code, action = "invalid_semantic_reference", (
            "使用本运行已查询的 publication_id、record_id、purpose；"
            "填写结论 report_quote 与 text_location，不要自行展开精确范围。"
        )
    elif "purpose" in message or "required_dependencies" in message:
        code, action = "invalid_purpose", (
            "证据用途与必要依赖仅支持 value/period/unit/header/footnote/condition/negation/attribution。"
        )
    elif "upsert" in message or "submission_mode" in message:
        code, action = "invalid_submission_mode", (
            "replace 提交完整清单；upsert 需任务身份和每条稳定 id，已绑定报告须沿用 report_path。"
        )
    elif ".id" in message:
        code, action = "invalid_conclusion_id", "每条结论 id 必须非空且唯一。"
    elif "conclusions 必须" in message:
        code, action = "empty_conclusions", "提交非空结论数组；未引用语料时无需提交清单。"
    elif "evidence" in message:
        code, action = "invalid_evidence", "提供非空 evidence 数组，每项使用已读原文的 evidence_ref。"
    problem: dict[str, Any] = {"code": code, "message": action}
    targets = list(dict.fromkeys(_FIELD_PATH.findall(message)))
    if targets:
        problem["targets"] = targets
    return problem


def project_manifest_result(full: dict[str, Any]) -> dict[str, Any]:
    """Keep validation states and repair targets, not expanded source records."""
    visible = {key: full[key] for key in (
        "ok", "submission_mode", "active_conclusion_ids", "evidence_status",
        "report_bound", "publish_status", "counts",
    ) if key in full}
    visible["hint"] = (
        "按结论 id 和 evidence_index 修正；引用用已读原文的 evidence_ref。"
        "pending 下一轮重提，无需重复 fetch。未绑定报告仅为证据预检；"
        "supported 表示溯源检查通过，不代表结论语义已证实。"
    )
    if full.get("errors"):
        visible["errors"] = [
            _schema_problem(part)
            for message in full["errors"]
            for part in re.split(r"; (?=conclusions\[)", str(message))
        ]
        if full.get("error_kind") == "report_binding":
            visible["errors"] = [{
                "code": "report_binding_error",
                "message": "report_path 必须指向已写入 /outputs 的可读 .md 或 .txt 报告。",
            }]
    if full.get("verification_error"):
        visible["evidence_status"] = visible["publish_status"] = "verification_error"
        visible["errors"] = [{
            "code": "verification_error", "message": _ACTIONS["verification_error"],
        }]
    rows = []
    for row in full.get("conclusions") or []:
        item = {key: row[key] for key in ("id", "status", "delivery") if key in row}
        missing = [purpose for purpose in row.get("missing_dependencies", []) if purpose in {
            "value", "period", "unit", "header", "footnote", "condition", "negation", "attribution",
        }]
        if missing:
            item["missing_dependencies"] = missing
        problems = []
        for problem in row.get("problems") or []:
            code = problem.get("code")
            out: dict[str, Any] = {
                "code": code if code in _ACTIONS else "validation_issue",
                "message": _ACTIONS.get(code, "校验未通过；检查本条结论的证据或移除结论。"),
            }
            match = re.match(r"evidence\[(\d+)\]", str(problem.get("message", "")))
            if match:
                out["evidence_index"] = int(match[1])
            problems.append(out)
        item["problems"] = problems
        # Preserve semantic delivery/version/quality outcomes without replaying
        # evidence_ranges, dependency_assertions or original source identities.
        semantic = row.get("semantic_references") or []
        if semantic:
            item["semantic_references"] = [
                {"index": index, **{key: ref[key] for key in (
                    "purpose", "delivery_status", "publication_status",
                    "quality_status", "verification_status",
                ) if key in ref}}
                for index, ref in enumerate(semantic)
            ]
        rows.append(item)
    if "conclusions" in full:
        visible["conclusions"] = rows
    return visible


def unavailable_manifest_result() -> dict[str, Any]:
    """Never spill the original body when metadata persistence fails."""
    return {
        "ok": False,
        "publish_status": "verification_error",
        "errors": [{
            "code": "metadata_snapshot_unavailable",
            "message": "校验回执保存失败，无法提供可追溯反馈；稍后重新提交确认。",
        }],
    }
