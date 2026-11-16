"""Shared final-answer contract; document identity never certifies source prose."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plugins.corpus.ledger import ConsumptionLedger


CORPUS_REPORT_STYLE_RULE = (
    "User-facing corpus prose must have readable citations: use the observed report title "
    "or filename and known page/section, or numbered citations with a readable source list. "
    "Never invent missing page numbers, titles or URLs. Keep opaque ce:/eref: receipts in "
    "structured evidence_ref fields, not in the displayed prose or reference list. "
    "Internal research handoffs may retain exact receipts. Prepare publication_excerpt text "
    "in this readable form BEFORE verification. Explain material missing evidence or unchecked "
    "claims in ordinary language; keep tool names, fetch_complete flags, check IDs and job IDs "
    "in audit data unless the user explicitly requests technical diagnostics."
)

# Match concrete receipts, not discussion of the ce:/eref: syntax itself.
_DISPLAYED_RECEIPT = re.compile(r"\b(?:ce:[0-9a-f]{16,}|eref:[0-9a-f]{16,}:\d+)\b")


def corpus_citation_readability_issue(content: str) -> str | None:
    """Detect opaque report citations without rewriting checked or bound text."""
    if not _DISPLAYED_RECEIPT.search(content):
        return None
    return (
        "corpus_citation_readability: displayed prose contains opaque corpus receipts. "
        + CORPUS_REPORT_STYLE_RULE
        + " Revise only the affected wording using existing evidence; no new fetch is needed "
        "for citation formatting. Rebind report_quote to the revised text and recheck any "
        "changed checked passage; never reuse a verdict for different text."
    )


#: 纯文件身份答案的交付形状——交付层的单一事实来源。
#:
#: 这段文字描述的是 ``identity_manifest`` 实际接受的形状，因此必须与它逐条对应：
#: prompt 允许的写法得不到解析器的承认时，模型会照规则写出被拒绝的答案（历史故障：
#: 加粗／「文件名：」前缀／空行分隔）。工具侧的清单说明不得复述这些规则，只回答
#: 「要不要提交清单」；两处交付提示（react 的最终答复检查、团队 ``deliver_answer``）
#: 与前置注入都引用本常量，避免同一契约在不同路径上分裂成两套措辞。
IDENTITY_ANSWER_RULE = (
    "纯文件身份答案的交付形状（只交付本轮实际检索到的 filename／document_title／"
    "已知发布日期，且发布日期确实由检索结果给出）：\n"
    "- 每个值单独一行，可用行内反引号；不得加粗，不得加列表符号或「文件名：」这类"
    "前缀标签，也不得用空行分隔——运行时按整行逐字比对文档身份；\n"
    "- 不需要依赖清单，也不需要例行 fetch；运行时按观测到的文档身份自动绑定；\n"
    "- 返回一个条目只证明存在、不证明覆盖，因此身份答案不需要「全库仅有／只有这一篇」"
    "这类缺席或覆盖声明；\n"
    "- 一旦答案还需要正文判断、说明或其余来源内容，就整条答案按正文证据契约提交清单，"
    "不要把它附加在身份列表之后。"
)


def identity_manifest(content: str, ledger: ConsumptionLedger) -> dict[str, Any] | None:
    """Recognize only exact observed identity values, with no explanatory prose.

    The ledger is populated by tool results, not model arguments. Keep bindings
    in the existing manifest artifact; there is no second receipt store.
    """
    from plugins.tools.corpus_manifest import prepare_final_manifest

    lines = content.strip().splitlines()
    if not lines or any(not line.strip() for line in lines):
        return None
    rows = []
    for index, line in enumerate(lines):
        value = line.strip()
        if value.startswith("`") and value.endswith("`"):
            value = value[1:-1]
        match = None
        for offered in ledger.document_identities:
            identity = offered.get("identity") or {}
            for field in ("filename", "document_title", "published"):
                if (
                    field == "published"
                    and identity.get("publication_date_basis", "unknown") == "unknown"
                ):
                    continue
                if identity.get(field) == value:
                    match = {
                        "doc_id": offered["doc_id"],
                        "build_id": offered["build_id"],
                        "field": field,
                        "value": value,
                    }
                    break
            if match:
                break
        if match is None:
            return None
        rows.append(
            {"id": f"identity-{index + 1}", "report_quote": line, "document_identity": match}
        )
    payload = prepare_final_manifest([], content.strip())
    payload["conclusions"] = rows
    return payload


def verify_identity_conclusion(
    conclusion: dict[str, Any],
    ledger: ConsumptionLedger,
    final_text: str | None,
) -> dict[str, Any]:
    expected = identity_manifest(final_text or "", ledger)
    valid = expected is not None and any(
        row["document_identity"] == conclusion.get("document_identity")
        and row["report_quote"] == conclusion.get("report_quote")
        for row in expected["conclusions"]
    )
    return {
        "id": conclusion.get("id"),
        "status": "supported" if valid else "unsupported",
        "verification_kind": "document_identity",
        "evidence_count": 0,
        "covered_purposes": [],
        "missing_dependencies": [],
        "delivery": [],
        "document_identity": conclusion.get("document_identity"),
        "problems": []
        if valid
        else [
            {
                "code": "invalid_document_identity",
                "message": "Answer is not an exact observed document identity",
            }
        ],
    }


def prepare_delivery_manifest(
    content: str,
    conclusions: list[dict[str, Any]] | None,
    ledger: ConsumptionLedger,
) -> dict[str, Any] | None:
    """Prepare the same content binding for team and single-agent delivery."""
    from plugins.tools.corpus_manifest import prepare_final_manifest

    if conclusions is not None:
        return prepare_final_manifest(conclusions, content.strip())
    identity = identity_manifest(content, ledger)
    if identity is not None:
        return identity
    if ledger.has_activity():
        raise ValueError(
            "Corpus-backed prose requires corpus_conclusions with id, exact report_quote and "
            "evidence:[{evidence_ref}]. Only exact observed filename/document_title/date values "
            "may omit the manifest. Do not append source-content claims to an identity answer."
        )
    return None
