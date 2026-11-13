"""语料分页策略 v2 的口径定义（单一事实来源）。

本模块**只声明契约**，不实现分页；实现见 ``plugins/tools/_corpus_document.py``。
上游（全文分页器、ReAct 后处理、团队后处理、外层结果 fitter）引用同一份常量，
避免"内部按一个口径装页、外层按另一个口径裁切"。

## 三组预算

1. **正文预算**（:data:`DOCUMENT_TEXT_BUDGET`）：按**原文**字符计量。v2 下
   ``max_chars`` 就是这个含义——6000 表示"最多 6000 个原文字符"，与信封大小无关。
2. **可见回执总预算**（:data:`DOCUMENT_VISIBLE_CAP`）：约束正文＋引用句柄＋必要
   提示的序列化总量。它是硬上限，由分页器与外层 fitter 共用。
3. **隐藏审计字段**（``text_sha256``／``evidence_ref``／``retry_cursor`` 等）：
   不占模型展示预算，但后台存储仍须有界（由看板侧上限约束，不在此定义）。

停止装页：正文预算或可见回执总预算，**任一先达到**即止。只加固定元数据 allotment
不够——引用与位置开销随 item 数增长，OCR 碎片尤其明显，必须实测最终可见 JSON。

## 版本契约

- 版本写入分页信封字段 ``pagination_policy_version``，写入 cursor 键 ``ppv``，
  并参与 ``page_id`` 哈希（:func:`document_page_id`）。
- 缺少策略字段的旧 cursor 按 v1 续读，**不得静默套用 v2**（:func:`policy_version`）。
- 不升级 :data:`plugins.corpus.cursor.CURSOR_SCHEMA_VERSION`：那是全部游标类型
  共用的绑定语义版本，升它会连带废掉 inventory／semantic 等无关游标。
- cursor 本身不含预算，因此"改预算口径"不会天然使旧租约失效；真正的风险是
  **同起点、同预算数字、内容不同却生成同一个 page_id**，这才是版本必须进哈希的原因。

## 覆盖口径

- 分母：目标文档版本的原始单元／字符范围。
- 分子：实际送达区间的并集（同文档＋同 locator＋同字符区间只算一次；不得按
  ``unit_id`` 去重，长单元跨页会误删续页正文）。
- 页数只是效率指标，**不能作为覆盖率分母**。
- ``native1``（检索）与 ``document1``（分页）两套 locator 通过后台映射关联，
  不强行归一成一种。
- 入库文本覆盖与原 PDF 提取完整性**分别记录**：已提取的 OCR 计入前者，不能因为
  "是 OCR"就把全部图像／表格内容排除在外。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

#: 当前分页策略版本。写入信封、cursor（``ppv``）并参与 ``page_id`` 哈希。
PAGINATION_POLICY_VERSION: Final = 2

#: 无策略字段时的版本：旧信封／旧游标一律按 v1 解释。
LEGACY_PAGINATION_POLICY_VERSION: Final = 1

#: cursor payload 中的策略版本键。
POLICY_VERSION_KEY: Final = "ppv"

#: 正文预算默认值（原文字符）。v2 下 ``max_chars`` 即此含义。
DOCUMENT_TEXT_BUDGET: Final = 6000

#: 正文预算下限：低于此值连一个可读片段都装不进，按预算错误拒绝，且不读库。
DOCUMENT_MIN_TEXT_BUDGET: Final = 256

#: 可见回执硬上限（序列化字符）：正文＋引用句柄＋必要提示的总量。
DOCUMENT_VISIBLE_CAP: Final = 12000

#: 覆盖统计的作用域：按文档单元／字符区间，而非检索 scope。
COVERAGE_SCOPE: Final = "document_units"


def policy_version(source: dict[str, Any] | None) -> int:
    """读策略版本；缺失或非法一律按 v1 解释，绝不默认成新策略。"""
    if not isinstance(source, dict):
        return LEGACY_PAGINATION_POLICY_VERSION
    raw = source.get("pagination_policy_version", source.get(POLICY_VERSION_KEY))
    if raw is None:
        return LEGACY_PAGINATION_POLICY_VERSION
    try:
        version = int(raw)
    except (TypeError, ValueError):
        return LEGACY_PAGINATION_POLICY_VERSION
    return version if version > 0 else LEGACY_PAGINATION_POLICY_VERSION


def document_page_id(
    *,
    doc_id: str,
    build_id: str,
    start_index: int,
    start_offset: int,
    effective_budget: int,
    version: int = PAGINATION_POLICY_VERSION,
    unit_range: tuple[int, int] | None = None,
    document_sha256: str = "",
    view: str = "compatible",
) -> str:
    """页身份：绑定文档版本、读取范围、起始位置、有效预算与策略版本。

    策略版本进哈希，是为了让"同样的起点和预算数字、不同算法"不可能生成同一个
    ``page_id``——否则 v1 与 v2 会在同一位置互相冒充，重放与同轮去重都会错。
    """
    material = json.dumps(
        {
            "v": int(version),
            "doc_id": str(doc_id),
            "build_id": str(build_id),
            "mi": int(start_index),
            "off": int(start_offset),
            "budget": int(effective_budget),
            "unit_range": unit_range,
            "document_sha256": document_sha256,
            "view": view,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return "docpage:" + hashlib.sha256(material.encode()).hexdigest()[:32]
