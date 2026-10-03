"""corpus_submit_manifest — 报告证据清单的**生产者**（A4 修订契约，评审 C3/C4）。

``corpus_search`` 给句柄、``corpus_fetch`` 给原文之后，结论要写进报告还需要一条
**可复算的溯源链**：结论 id、报告定位锚点、逐字引文及其在权威原文中的位置、必要
依赖（期间／单位／表头／脚注）。本工具是清单的生产入口：

- **schema 先行**：非法结论／证据条目在入口即拒绝（非对象、缺 doc_id/locator/quote、
  杜撰 purpose），绝不静默跳过——权威校验器（``plugins.corpus.ledger``）不信任清单，
  入口放进的垃圾只会在边界变成 unsupported；
- **独立落盘 + 同拥有者取代**：每次提交写独立子清单文件（``<APODEX_RUN_DIR>/corpus/
  manifests/manifest-NNN.json``），多代理／多次提交互不覆盖，最终报告边界统一汇总
  校验（评审 C4：共享单文件会被后提交的子代理整体覆盖）。落盘时写入 ``owner_role``
  （当前代理实例的 ``ExecutionScope.task_id``）；边界聚合**跨拥有者并集、同拥有者
  取最新**——同一代理「重新提交完整清单」取代自己先前的候选，不同代理之间互补；
- **即时回验**：提交后立即由账本 + 权威原文重算每条结论状态并随结果返回，
  问题（quote 编造／引文区间未送达／依赖缺失）直接反馈给模型驱动**环内修正**；
  新取片段尚未经过下一轮消息边界核验时如实标 ``pending``，提示下一轮重新提交
  确认（评审 C3：不靠退出时补账，也不诱发无效补取）；
- **报告锚点**：``report_quote`` 是该结论在**最终报告**里的逐字锚点，提交时可缺省
  （报告尚未成文），但边界汇总校验时缺锚点或锚点不在最终报告中会记
  ``not_in_report`` 并把发布状态压到 ``partial``。

纪律：本工具只写 run 工件目录，不碰语料库；重复提交以**新文件**追加，历史候选
全部保留供审计。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.tool import tool
from plugins.corpus.ledger import (
    DEPENDENCY_PURPOSES,
    MANIFEST_SCHEMA_VERSION,
    SourceResolver,
    evidence_delivery_for_submit,
    get_run_ledger,
    verify_manifest,
    write_manifest_file,
)
from plugins.corpus.service import get_service
from plugins.corpus.structured.consumption import (
    ReportSemanticReference,
    reference_for_record,
)

logger = logging.getLogger(__name__)

_SUBMIT_HINT = (
    "对非 supported 的结论：按需补取原文、重新查询失效语义版本、修改表述或移除结论；"
    "已完整送达的语义证据不必例行 corpus_fetch。"
    "然后重新提交**完整**清单（每次提交生成新的候选文件，边界以汇总校验为准）。"
    "本轮新取的片段需经过下一轮消息边界核验，pending 的结论请下一轮重新提交确认。"
)

#: 触发伴随绑定的语料检索工具（任一出现即注入清单生产者）。
CORPUS_RETRIEVAL_TOOLS = frozenset({"corpus_search", "corpus_fetch", "corpus_semantic_query"})
MANIFEST_TOOL_NAME = "corpus_submit_manifest"


def with_manifest_tool(tools: list[Any], *, role_id: str) -> list[Any]:
    """语料检索工具的**伴随绑定**：绑定检索即绑定清单生产者（评审 C4 配套）。

    与 ``web_fetch``→``download_file`` 的伴随先例同构——profile 少配不会静默
    降级为「无清单报告」（发布边界恒 draft），而是补齐并记日志。
    """
    names = {getattr(item, "name", "") for item in tools}
    if not names & CORPUS_RETRIEVAL_TOOLS or MANIFEST_TOOL_NAME in names:
        return tools
    logger.info(
        "A4 manifest tool auto-bound for %s (companion of %s)",
        role_id, sorted(names & CORPUS_RETRIEVAL_TOOLS),
    )
    return [*tools, corpus_submit_manifest]


#: 系统提示附注：清单提交义务（仅在工具实际绑定时追加）。
MANIFEST_PROMPT_NOTE = (
    "\n\n## 报告证据清单（A4）\n"
    "你绑定了 `corpus_submit_manifest`。在产出基于语料库结论的报告或最终回复之前：\n"
    "1. 把每条基于语料的结论登记进清单：结论 id、`report_quote`（该结论在最终报告"
    "中的逐字锚点）、逐字 `quote` 证据（doc_id/locator/quote）与必要依赖"
    "（period/unit/header/footnote 用途）；\n"
    "2. 按工具返回的逐条问题修正：补取原文（corpus_fetch）、修改表述或移除结论，"
    "然后重新提交完整清单；\n"
    "3. 新取片段下一轮才能确认送达（pending），届时重新提交确认；\n"
    "4. 最终报告不得主张清单标记为 unsupported 的结论。\n"
    "5. 若使用 corpus_semantic_query 已送达的完整原文，可用 semantic_references："
    "每项给 publication_id、record_id、purpose（cite/compare/calculate）；系统从本运行"
    "查询记录补齐精确原文范围及依赖，生成正式语义报告引用，无需例行 fetch。"
    "仍须填写结论 report_quote 与 text_location；用途许可不同于 value/condition 等依赖作用。"
    "pending 等待下一轮实际请求确认；裁剪缺口重查，版本失效须重查，不能把发布成功当送达。\n"
    "发布边界会对照最终报告与消费账本重算校验；缺清单或未通过都会被记录并"
    "（在启用阻断时）降级发布状态。"
)


def _validate_conclusions(conclusions: Any) -> list[str]:
    """入口 schema 校验：返回错误列表（空 = 通过）。绝不抛。"""
    errors: list[str] = []
    if not isinstance(conclusions, list) or not conclusions:
        return ["conclusions 必须是非空数组"]
    for index, row in enumerate(conclusions):
        label = f"conclusions[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label} 不是 JSON 对象")
            continue
        evidence = row.get("evidence")
        semantic = row.get("semantic_references")
        if semantic is not None:
            if not isinstance(semantic, list) or not semantic:
                errors.append(f"{label}.semantic_references 必须为非空数组")
            else:
                for item in semantic:
                    try:
                        ref = ReportSemanticReference.model_validate(item)
                        if ref.report_quote != row.get("report_quote"):
                            errors.append(f"{label} 语义引用 report_quote 不一致")
                    except ValueError as exc:
                        errors.append(f"{label} 语义引用无效: {exc}")
        if evidence is None and semantic is not None:
            evidence = []
        if not isinstance(evidence, list) or (not evidence and semantic is None):
            errors.append(f"{label} 缺少非空 evidence 数组")
            continue
        for ev_index, item in enumerate(evidence):
            ev_label = f"{label}.evidence[{ev_index}]"
            if not isinstance(item, dict):
                errors.append(f"{ev_label} 不是 JSON 对象")
                continue
            for field in ("doc_id", "locator", "quote"):
                if not str(item.get(field) or "").strip():
                    errors.append(f"{ev_label} 缺少 {field}")
            purpose = str(item.get("purpose") or "").strip()
            if purpose and purpose not in DEPENDENCY_PURPOSES:
                errors.append(
                    f"{ev_label}.purpose={purpose!r} 不在用途词表 "
                    f"{list(DEPENDENCY_PURPOSES)} 内",
                )
        for dep in row.get("required_dependencies") or []:
            if str(dep) not in DEPENDENCY_PURPOSES:
                errors.append(
                    f"{label}.required_dependencies 含未知依赖 {dep!r}"
                    f"（词表：{list(DEPENDENCY_PURPOSES)}）",
                )
    return errors


def _expand_semantic_references(conclusions: Any) -> Any:
    """Resolve short record selections to frozen references, never to delivered flags."""
    if not isinstance(conclusions, list):
        return conclusions
    rows = []
    for row in conclusions:
        if not isinstance(row, dict) or not isinstance(row.get("semantic_references"), list):
            rows.append(row)
            continue
        references = []
        for item in row["semantic_references"]:
            if not isinstance(item, dict) or set(item) != {"publication_id", "record_id", "purpose"}:
                references.append(item)
                continue
            observations = get_run_ledger().semantic.observations(
                item["publication_id"], item["record_id"],
            )
            if not observations:
                raise ValueError("所选语义记录未由本运行的真实查询返回")
            record = next(r for r in observations[0].page.records if r.record_id == item["record_id"])
            ref = reference_for_record(
                item["publication_id"], record, item["purpose"],
                str(row.get("text_location") or row.get("id") or ""),
                str(row.get("report_quote") or ""),
            )
            references.append(ref.model_dump(mode="json"))
        rows.append({**row, "semantic_references": references})
    return rows


def _current_owner() -> str:
    """当前代理实例的稳定标识，用作清单的拥有者（聚合键）。

    取当前 ``ExecutionScope`` 的 ``task_id``：每个代理实例一个，且在该代理的多次
    提交之间不变——于是「同代理重新提交」取代自己先前的候选，而不同代理／子代理
    之间仍跨拥有者并集（评审 C4）。取不到时返回空串，落盘退回文件名语义。
    """
    scope = get_current_execution_scope()
    if scope is None:
        return ""
    task_id = str(getattr(scope, "task_id", "") or "").strip()
    role_id = str(getattr(scope, "role_id", "") or "").strip()
    if task_id and role_id:
        return f"{role_id}:{task_id}"
    return task_id or role_id


@tool
async def corpus_submit_manifest(conclusions: list[dict[str, Any]]) -> str:
    """提交报告结论证据清单（A4），立即回验并返回逐条问题以驱动环内修正。

    在报告成稿（或最终回复撰写）**之前**调用：把报告中每条基于语料的结论登记成
    可复算的溯源链。每次提交生成独立候选文件，重复提交不覆盖历史；最终发布边界
    会汇总全部候选并对照最终报告与消费账本重算校验。

    Args:
        conclusions: 结论数组。每条结论：
            ``id``（可选，缺省自动编号）、``text_location``（结论文本位置描述）、
            ``report_quote``（该结论在**最终报告**中的逐字锚点；报告未成文时可先
            缺省，边界校验时必须能定位）、``evidence``（非空数组，每项含
            ``doc_id``／``locator``／``quote``（权威原文逐字片段）及可选
            ``purpose``：value|period|unit|header|footnote|condition|negation|attribution）、
            ``required_dependencies``（可选，结论成立必需的用途列表，须与某条
            证据的 purpose 对应）。语义查询证据可改用 ``semantic_references``
            数组（可与 evidence 并存），每项含 ``publication_id/record_id/purpose``；
            purpose 为 cite|compare|calculate，非依赖作用。必须同时给 report_quote
            和 text_location（或 id）。也可提交完整 corpus-report-semantic-reference-v1
            引用，但状态字段不被信任，精确范围/依赖/送达/版本均由后台重算。

    Returns:
        JSON：``ok``、``manifest_file``（落盘路径，无 run 目录为 null）、
        ``publish_status``（supported/partial/unsupported 计数汇总）、
        ``conclusions``（逐条状态与问题，pending=新取片段待下一轮边界核验）、
        ``hint``（修正指引）；schema 不合法时 ``ok=false`` 且 ``errors`` 逐条列出。
    """
    try:
        conclusions = _expand_semantic_references(conclusions)
        errors = _validate_conclusions(conclusions)
    except (ValueError, TypeError) as exc:
        errors = [str(exc)]
    if errors:
        return json.dumps(
            {
                "ok": False,
                "errors": errors,
                "hint": "修正上述 schema 问题后重新提交完整清单",
            },
            ensure_ascii=False,
        )

    rows = [row for row in conclusions if isinstance(row, dict)]  # schema 已保证
    numbered: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        entry = dict(row)
        entry.setdefault("id", f"C{index + 1}")
        numbered.append(entry)

    owner = _current_owner()
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "conclusions": numbered,
    }
    path = write_manifest_file(payload, owner=owner)

    # 即时回验（评审 C3）：用当前送达快照重算，新取片段标 pending；环内无最终
    # 报告文本，不做 report_quote 锚点检查（那是发布边界的事）。
    ledger = get_run_ledger()
    resolve = _resolver()
    try:
        verification = verify_manifest(
            payload, ledger, resolver=resolve, pending_aware=True,
        )
    except Exception as exc:
        return json.dumps(
            {
                "ok": True,
                "manifest_file": str(path) if path else None,
                "owner": owner or None,
                "verification_error": f"{type(exc).__name__}: {exc}",
                "hint": "校验基础设施故障；请稍后重新提交确认",
            },
            ensure_ascii=False,
        )

    conclusions_out = []
    for row in verification.get("conclusions") or []:
        problems = []
        for problem in row.get("problems") or []:
            problems.append({"code": problem.get("code"), "message": problem.get("message")})
        conclusions_out.append({
            "id": row.get("id"),
            "status": row.get("status"),
            "delivery": row.get("delivery"),
            "semantic_references": row.get("semantic_references", []),
            "problems": problems,
        })
    return json.dumps(
        {
            "ok": True,
            "manifest_file": str(path) if path else None,
            "owner": owner or None,
            "publish_status": verification.get("status"),
            "counts": verification.get("counts"),
            "conclusions": conclusions_out,
            "hint": _SUBMIT_HINT,
        },
        ensure_ascii=False,
    )


def _resolver() -> SourceResolver:
    """权威原文 resolver：延迟构造，异常交给 verify_manifest 逐条分类。"""
    def resolve(doc_id: str, locator: str) -> str | None:
        return get_service().fetch_verbatim(doc_id, locator).text

    return resolve


def submit_delivery_status(
    ledger: Any, doc_id: str, locator: str, quote: str, source_text: str | None,
) -> str:
    """单条证据的送达状态（供测试与诊断用）：把 quote 定位到区间再查覆盖。"""
    if source_text is None:
        return "unknown"
    offset = source_text.find(quote)
    if offset < 0:
        return "unknown"
    return evidence_delivery_for_submit(
        ledger, doc_id, locator, offset, offset + len(quote),
    )
