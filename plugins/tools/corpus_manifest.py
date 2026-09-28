"""corpus_submit_manifest — 报告证据清单的**生产者**（A4 修订契约，评审 C3/C4）。

``corpus_search`` 给句柄、``corpus_fetch`` 给原文之后，结论要写进报告还需要一条
**可复算的溯源链**：结论 id、报告定位锚点、逐字引文及其在权威原文中的位置、必要
依赖（期间／单位／表头／脚注）。本工具是清单的生产入口：

- **schema 先行**：非法结论／证据条目在入口即拒绝（非对象、缺 doc_id/locator/quote、
  杜撰 purpose），绝不静默跳过——权威校验器（``plugins.corpus.ledger``）不信任清单，
  入口放进的垃圾只会在边界变成 unsupported；
- **独立落盘**：每次提交写独立子清单文件（``<APODEX_RUN_DIR>/corpus/manifests/
  manifest-NNN.json``），多代理／多次提交互不覆盖，最终报告边界统一汇总校验
  （评审 C4：共享单文件会被后提交的子代理整体覆盖）；
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

logger = logging.getLogger(__name__)

_SUBMIT_HINT = (
    "对非 supported 的结论：补取原文（corpus_fetch）、修改报告表述或从报告中移除，"
    "然后重新提交**完整**清单（每次提交生成新的候选文件，边界以汇总校验为准）。"
    "本轮新取的片段需经过下一轮消息边界核验，pending 的结论请下一轮重新提交确认。"
)

#: 触发伴随绑定的语料检索工具（任一出现即注入清单生产者）。
CORPUS_RETRIEVAL_TOOLS = frozenset({"corpus_search", "corpus_fetch"})
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
        if not isinstance(evidence, list) or not evidence:
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
            ``purpose``：value|period|unit|header|footnote）、
            ``required_dependencies``（可选，结论成立必需的用途列表，须与某条
            证据的 purpose 对应）。

    Returns:
        JSON：``ok``、``manifest_file``（落盘路径，无 run 目录为 null）、
        ``publish_status``（supported/partial/unsupported 计数汇总）、
        ``conclusions``（逐条状态与问题，pending=新取片段待下一轮边界核验）、
        ``hint``（修正指引）；schema 不合法时 ``ok=false`` 且 ``errors`` 逐条列出。
    """
    errors = _validate_conclusions(conclusions)
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

    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "conclusions": numbered,
    }
    path = write_manifest_file(payload)

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
            "problems": problems,
        })
    return json.dumps(
        {
            "ok": True,
            "manifest_file": str(path) if path else None,
            "publish_status": verification.get("status"),
            "counts": verification.get("counts"),
            "conclusions": conclusions_out,
            "hint": _SUBMIT_HINT,
        },
        ensure_ascii=False,
    )


def _resolver() -> SourceResolver:
    """权威原文 resolver：延迟构造，异常交给 verify_manifest 逐条分类。"""
    service = get_service()

    def resolve(doc_id: str, locator: str) -> str | None:
        return service.fetch_verbatim(doc_id, locator).text

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
