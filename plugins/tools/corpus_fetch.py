"""corpus_fetch — 按取证句柄取回**逐字**原文。

硬闸①「数字可溯源」的在线落点：``evidence.quote`` 必须来自这里返回的文本，
而不是来自 ``corpus_search`` 的 snippet，更不是来自模型的记忆。

设计上刻意只做一件事——给 ``(doc_id, locator)`` 返回该块原文，
不做摘要、不做改写；结构性上下文以明确单元标识附带，逐单元哈希验证，
单元间以换行分隔，spans 保留各单元精确范围。
而离线校验正是靠逐字比对来抓编造的。

句柄契约（架构 §7.2，I2-8）：

- ``doc_id`` = ``cv2:<build_id>``：一个确切文档构建版本，可原样复制，不需要模型生成 ID；
- ``locator`` = ``chunk:<chunk_id>``：该 build 内的确切检索块；
- 引用的 ``text`` 来自权威 ``corpus_units.raw_text``（不是清洗视图、不是检索展示）；
- search 与 fetch 之间发生新版本发布时，旧句柄仍读取其原 build，不静默切换；
- 旧句柄（无 ``cv2:`` 前缀）显式拒绝（``archive_required``），不拿新链正文顶替。
"""

from __future__ import annotations

import json

from frontier_agent.core.tool import tool
from plugins.corpus.preparation.read_pg import AUTHORITY_REV
from plugins.corpus.service import get_service


@tool
async def corpus_fetch(doc_id: str, locator: str) -> str:
    """取回语料中指定块的逐字原文，用于写入 ``evidence.quote``。

    在 ``corpus_search`` 之后调用：search 给句柄，本工具给原文。

    Args:
        doc_id: 版本句柄（来自 ``corpus_search`` 的 ``doc_id``，形如 ``cv2:<build_id>``）。
        locator: 块句柄（来自 ``corpus_search`` 的 ``locator``，形如 ``chunk:<chunk_id>``）。

    Returns:
        JSON 字符串：``{"ok": true, "doc_id", "locator", "text", "source_id",
        "build_id", "chunk_id", "units"}``。句柄失效/旧句柄/来源已撤销时返回
        ``ok=false`` 并在 ``error`` 里给出原因（``archive_required`` 表示旧引用）。
    """
    if not isinstance(doc_id, str) or not doc_id.strip():
        return json.dumps(
            {"ok": False, "error": "doc_id 必须是非空字符串"},
            ensure_ascii=False,
        )

    # I2-8：旧句柄（无 cv2: 前缀）不得拿新链正文顶替——显式 archive_required。
    if not doc_id.startswith("cv2:"):
        return json.dumps(
            {
                "ok": False,
                "error": "archive_required：该 doc_id 是旧句柄（非 cv2:<build_id>），"
                "新链不以其取正文，也不以新版本冒称旧引用；"
                "历史引用请走已归档副本解释，或重新检索取得当前版本句柄。",
                "doc_id": doc_id,
                "locator": locator if isinstance(locator, str) else None,
            },
            ensure_ascii=False,
        )

    try:
        svc = get_service()
        evidence = svc.fetch_verbatim(doc_id, locator)
        semantic_cells = svc.emit_cells(evidence)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": f"取证失败（句柄不可解析、跨 build 或来源已撤销）：{exc}"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "ok": True,
            "doc_id": doc_id,
            "locator": locator,
            "source_id": evidence.source_id,
            "build_id": evidence.build_id,
            "chunk_id": evidence.chunk_id,
            "kind": evidence.kind,
            "active": evidence.active,
            "authority_rev": AUTHORITY_REV,
            "context_unit_ids": list(evidence.context_unit_ids),
            "units": [
                {
                    "unit_id": unit.unit_id,
                    "page": unit.page,
                    "element": unit.element,
                    "cells": [list(cell) for cell in unit.cells],
                }
                for unit in evidence.units
            ],
            "semantic_cells": [
                {
                    "unit_id": cell.unit_id,
                    "page": cell.page,
                    "row": cell.row,
                    "col": cell.col,
                    "text": cell.text,
                }
                for cell in semantic_cells
            ],
            # 权威原文 code point 区间（§4.2，来自 corpus_chunks.source_ranges）
            "source_ranges": [list(span) for span in evidence.source_ranges],
            # 每个单元在**本 text** 内的偏移 (unit_id, start, end)：切片可复算出 text
            "spans": [
                {"unit_id": unit_id, "start": start, "end": end}
                for unit_id, start, end in evidence.spans
            ],
            "text": evidence.text,
            "hint": (
                "evidence.quote 必须逐字取自本 text；evidence.page 填本 locator；"
                "跨 unit 的精确区间用 spans（text 内偏移）与 source_ranges（原文 code point）。"
            ),
        },
        ensure_ascii=False,
    )
