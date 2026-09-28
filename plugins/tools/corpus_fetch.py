"""corpus_fetch — 按取证句柄取回**逐字**原文（单块 / 批量 / 游标分页）。

硬闸①「数字可溯源」的在线落点：``evidence.quote`` 必须来自这里返回的文本，
而不是来自 ``corpus_search`` 的 snippet，更不是来自模型的记忆。

设计上只做一件事——给 ``(doc_id, locator)`` 返回该块原文，不做摘要、不做改写；
结构性上下文以明确单元标识附带，逐单元哈希验证，单元间以换行分隔，spans 保留各单元
精确范围。离线校验正是靠逐字比对来抓编造的。

入口（A2.1）：``locator``、``locators``、``cursor`` **恰选其一**。

- **单块（``locator``）**：结果装得下时维持既有单块字段语义（``ok/text/spans/
  source_ranges/kind/build_id/...``）原样返回，不改变既有消费者；
- **批量（``locators``）／游标（``cursor``）**：一致的分页信封（A2.2）；
- **单块超限**：显式分片为信封，不悄悄改写为「已取得全文」。

两种返回视图（A0.1／A0.2）：

- ``view="full"``（默认）：保留诊断／结构元数据，供审计、产品观测与既有消费者；
- ``view="compact"``：正文优先的精简视图，去掉大体量几何元数据，只保留引用所需
  最小映射、单元身份、结构状态，以及**可解析**回完整元数据的引用。
  游标模式下视图由游标决定，调用方不得借该参数切换。

分片与预算（A2.3）：

- 正文块超限优先在段落／句读边界分片，必要时按 Unicode 码点边界硬分；
- 表格块只按完整行分片，**绝不硬切半个单元格**；最小原子单元仍超限则返回
  ``unit_too_large`` 并给出所需容量；
- 分片用 ``fragment.start/end`` 标注**本块 ``text`` 内的 Unicode 码点区间**，
  并附整块内容身份（``text_sha256``／``text_chars``）供校验；
- ``exhausted`` 只表示这轮游标遍历到终点；有失败／未完成时 ``fetch_complete`` 仍为
  false，失败成员保留在 ``unresolved``（不得靠游标前移当作成功）。

结构化结果的预算处理（A0.3）：:func:`fit_structured_payload` 供工作流后处理与单轮
聚合预算统一调用——超预算时先去诊断元数据（等价 compact），始终返回**合法 JSON**；
正文本身装不下时返回可识别的预算错误，绝不按字符硬切 JSON，也不返回残缺正文。

句柄契约（架构 §7.2，I2-8）：

- ``doc_id`` = ``cv2:<build_id>``：一个确切文档构建版本，可原样复制，不需要模型生成 ID；
- ``locator`` = ``chunk:<chunk_id>``：该 build 内的确切检索块；
- 引用的 ``text`` 来自权威 ``corpus_units.raw_text``（不是清洗视图、不是检索展示）；
- search 与 fetch 之间发生新版本发布时，旧句柄仍读取其原 build，不静默切换；
- 旧句柄（无 ``cv2:`` 前缀）显式拒绝（``archive_required``），不拿新链正文顶替。
"""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from typing import Any

from frontier_agent.core.tool import tool
from plugins.corpus.cursor import CONTENT, CursorError, decode_cursor, encode_cursor
from plugins.corpus.preparation.read_pg import AUTHORITY_REV
from plugins.corpus.service import content_role_for_kind, context_scope_id, get_service

#: 允许的返回视图；未知取值 fail-closed 拒绝，不静默退回默认视图。
_VALID_VIEWS = ("full", "compact")

#: 分页页信封 schema 版本（与游标绑定，变更即显式失效）。
_SCHEMA_VERSION = 1

#: 分页预算下限：低于此值连页信封都装不下，直接返回可识别的预算错误。
_MIN_BUDGET = 400

#: 片段文本预算之外的固定余量（键名、数字位数、转义等抖动），避免「刚好塞满」。
_MARGIN = 64

#: 正文优先的引用提示（full 视图）。
_FULL_HINT = (
    "evidence.quote 必须逐字取自本 text；evidence.page 填本 locator；"
    "跨 unit 的精确区间用 spans（text 内偏移）与 source_ranges（原文 code point）。"
    "kind=heading 时 content_role=heading_only：只证明标题被取回，不含表体／数值。"
    "relations 是**本次请求范围**内的结构关联（verified=持久化结构树／表题证明，"
    "candidate=同章节邻接），候选不得当作已满足表体依赖。"
)
#: compact 视图提示：额外说明如何取回被省去的诊断元数据。
_COMPACT_HINT = (
    _FULL_HINT + "需要完整几何／诊断元数据时，用 meta_ref 的 doc_id、locator 以 "
    'view="full" 复取（同一 build，可由 spans 复算本段文本）。'
)
#: 分页信封提示。
_PAGE_HINT = (
    "本页 items 是取回的正文（可能为整块或分片）；quote 必须逐字取自 item.text。"
    "分片用 fragment.start/end 标注**本块 text 内**的 Unicode 码点区间，"
    "text_sha256/text_chars 是整块内容身份，可用于校验分片确来自该块。"
    "续取用 next_cursor；exhausted 只表示这轮遍历到终点——有失败项时 fetch_complete "
    "仍为 false 且见 unresolved，不得把游标前移当作已取全。"
    "kind=heading 的 item content_role=heading_only（只证明标题被取回）；relations 是"
    "本次请求范围内的结构关联（verified／candidate 严格分开）。"
)

#: 正文块的优先切分边界（按出现顺序尝试，越靠前越优先）。
_TEXT_BREAKS = ("\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";")
#: 表格块只按整行切分，避免硬切半个单元格。
_TABLE_BREAKS = ("\n",)


class _AtomTooLarge(Exception):
    """最小原子单元（表格整行）本身超过片段预算。"""

    def __init__(self, start: int, end: int) -> None:
        super().__init__(f"最小原子单元 {end - start} 字符超过片段预算")
        self.chars = end - start


def _json_error(message: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _dedupe_locators(locators: list[str]) -> list[str]:
    """批量输入按首次出现去重并固定顺序（A2.1）。"""
    seen: set[str] = set()
    out: list[str] = []
    for locator in locators:
        if not isinstance(locator, str) or not locator.strip():
            raise ValueError("locators 必须是非空字符串列表")
        if locator not in seen:
            seen.add(locator)
            out.append(locator)
    return out


def _error_code(exc: Exception) -> str:
    from plugins.corpus.preparation import read_pg

    if isinstance(exc, read_pg.LegacyHandleError):
        return "archive_required"
    if isinstance(exc, read_pg.UnknownHandleError):
        return "unknown_handle"
    if isinstance(exc, read_pg.WithdrawnError):
        return "withdrawn"
    if isinstance(exc, read_pg.IntegrityError):
        return "integrity"
    return "fetch_failed"


def _break_points(text: str, kind: str, start: int) -> list[int]:
    tokens = _TABLE_BREAKS if kind == "table" else _TEXT_BREAKS
    points: set[int] = set()
    for token in tokens:
        idx = text.find(token, start)
        while idx >= 0:
            end = idx + len(token)
            if end > start:
                points.add(end)
            idx = text.find(token, end)
    return sorted(points)


def _fragment_ranges(text: str, kind: str, budget: int, start: int) -> list[tuple[int, int]]:
    """把 ``text[start:]`` 打包为片段：优先原子边界，表格原子超限即拒绝。"""
    n = len(text)
    if start >= n:
        return []
    bounds = [start, *(cut for cut in _break_points(text, kind, start) if cut < n), n]
    pieces: list[tuple[int, int]] = []
    for atom_start, atom_end in pairwise(bounds):
        if atom_end <= atom_start:
            continue
        if kind == "table" and atom_end - atom_start > budget:
            raise _AtomTooLarge(atom_start, atom_end)
        cursor = atom_start
        while atom_end - cursor > budget:
            pieces.append((cursor, cursor + budget))
            cursor += budget
        pieces.append((cursor, atom_end))
    merged: list[tuple[int, int]] = []
    for piece_start, piece_end in pieces:
        if merged and piece_end - merged[-1][0] <= budget:
            merged[-1] = (merged[-1][0], piece_end)
        else:
            merged.append((piece_start, piece_end))
    return merged


def _pages_for(evidence: Any, start: int, end: int) -> list[int]:
    """分片 ``[start, end)`` 覆盖到的单元页码（同块 text 内偏移，来自 spans）。"""
    pages: set[int] = set()
    units_by_id = {unit.unit_id: unit for unit in evidence.units}
    for unit_id, unit_start, unit_end in evidence.spans:
        if unit_start < end and start < unit_end:
            unit = units_by_id.get(unit_id)
            if unit is not None and unit.page is not None:
                pages.add(unit.page)
    return sorted(pages)


def _evidence_structure_status(svc: Any, evidence: Any) -> str:
    if svc.emit_cells(evidence):
        return "verified"
    if any(unit.cells for unit in evidence.units):
        return "partial"
    return "unknown"


def _page_id(scope_id: str, member_index: int, offset: int, budget: int) -> str:
    """页身份：范围身份 + 起始位置（成员下标 + 块内偏移）+ 有效预算。

    固定游标 + 相同有效预算重放 → 同一 ``page_id``（A2.2 可重放性）。
    """
    digest = hashlib.sha256(f"{scope_id}|{member_index}|{offset}|{budget}".encode()).hexdigest()
    return f"fpage:{digest[:16]}"


def _content_cursor(
    doc_id: str,
    build_id: str,
    request: list[str],
    view: str,
    member_index: int,
    offset: int,
    unresolved: list[str],
) -> str:
    return encode_cursor(
        {
            "type": CONTENT,
            "doc_id": doc_id,
            "build_id": build_id,
            "req": list(request),
            "view": view,
            "mi": member_index,
            "off": offset,
            "unresolved": list(unresolved),
        }
    )


def _item(
    evidence: Any,
    locator: str,
    start: int,
    end: int,
    view: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = evidence.text
    whole = start == 0 and end == len(text)
    item: dict[str, Any] = {
        "locator": locator,
        "chunk_id": evidence.chunk_id,
        "kind": evidence.kind,
        "build_id": evidence.build_id,
        "text": text[start:end],
        "pages": _pages_for(evidence, start, end) or None,
        "fragment": None if whole else {"start": start, "end": end, "of_chars": len(text)},
        "text_chars": len(text),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "structure_status": status,
    }
    if extra:  # A3：content_role／relations／relation_status（小字段，正文之后、诊断之前）
        item.update(extra)
    if view == "full":
        item["units"] = [{"unit_id": unit.unit_id, "page": unit.page} for unit in evidence.units]
    return item


def _structure_status(payload: dict[str, Any]) -> str:
    """A0.2 结构状态（与 A1 词汇一致），只依据实际可核验的结构证据：

    - ``verified``：存在已核验的对齐单元（网格投影成功）；
    - ``partial``：存在单元几何坐标、但未形成可核验的对齐标签；
    - ``unknown``：没有任何结构依据。

    未知一律填 ``unknown``，不补造行列、不用 0 冒充"没有结构"。
    """
    cells = payload.get("semantic_cells")
    if isinstance(cells, list) and cells:
        return "verified"
    units = payload.get("units")
    if isinstance(units, list) and any(
        isinstance(unit, dict) and unit.get("cells") for unit in units
    ):
        return "partial"
    return "unknown"


def _compact_payload(full: dict[str, Any]) -> dict[str, Any]:
    """从 full 结果派生紧凑视图（A0.2）：正文优先 + 最小引用映射 + 结构状态 + 可解析引用。

    去掉大体量几何元数据（``units[].cells`` 与 ``semantic_cells`` 全量），只保留
    页码／单元身份与结构状态；完整元数据由 ``meta_ref``（固定同一 build 与内容身份）
    可解析地取回。
    """
    units_in = full.get("units")
    units = (
        [
            {"unit_id": unit.get("unit_id"), "page": unit.get("page")}
            for unit in units_in
            if isinstance(unit, dict)
        ]
        if isinstance(units_in, list)
        else []
    )
    cells = full.get("semantic_cells")
    cell_count = len(cells) if isinstance(cells, list) else 0
    compact: dict[str, Any] = {
        "ok": True,
        "view": "compact",
        "doc_id": full.get("doc_id"),
        "locator": full.get("locator"),
        "kind": full.get("kind"),
        "build_id": full.get("build_id"),
        "text": full.get("text"),
        "spans": full.get("spans"),
        "source_ranges": full.get("source_ranges"),
    }
    for key in ("content_role", "relations", "relation_status"):
        if key in full:
            compact[key] = full[key]
    compact.update(
        {
            "units": units,
            "structure_status": _structure_status(full),
            "structure_cells": cell_count,
            "meta_ref": {
                "doc_id": full.get("doc_id"),
                "locator": full.get("locator"),
                "build_id": full.get("build_id"),
                "chunk_id": full.get("chunk_id"),
                "view": "full",
            },
            "hint": _COMPACT_HINT,
        }
    )
    return compact


def _compact_envelope(payload: dict[str, Any]) -> str:
    """分页信封（A2.2）的协议压缩：保留 ``items`` 正文与续取控制字段，只去掉诊断性的
    ``units`` 单元清单（等价 compact 视图）。

    信封与单块结果**形状不同、语义也不同**：信封的正文在 ``items`` 里，续取靠
    ``next_cursor``。此前把 ``ok: true`` 的信封当成单块结果交给 ``_compact_payload``，
    会把 ``items`` 整个丢掉——正文、句柄、游标一起消失，只剩一个 ``text: null`` 的空壳，
    正是「静默丢证据」。此处按信封语义压缩。
    """
    out = dict(payload)
    out["items"] = [
        {key: value for key, value in item.items() if key != "units"}
        for item in (payload.get("items") or [])
        if isinstance(item, dict)
    ]
    out["diagnostics_elided"] = True
    out["view_fallback"] = "compact"
    return json.dumps(out, ensure_ascii=False)


def fit_structured_payload(body: str, budget: int) -> str | None:
    """A0.3：把 corpus_fetch 的结构化 JSON 结果压进 ``budget``，始终返回**合法 JSON**。

    供工作流后处理与单轮聚合预算统一调用，替代按字符硬切 JSON。两种返回形状分别处理，
    绝不混用（混用会静默丢正文）：

    - 结果本身 ≤ ``budget``：原样返回；
    - **分页信封**（含 ``items``）：去掉诊断性的 ``units`` 清单，正文与续取控制字段原样保留；
      仍装不下则返回可识别的预算错误，并带上 ``next_cursor``／``unresolved`` 供续取判断；
    - **单块结果**：先去诊断元数据（等价 compact 视图）再序列化；能装下即返回，
      并标记 ``diagnostics_elided``；去诊断后正文仍超预算则返回预算错误；
    - 一律不返回残缺正文、不伪造「已取得全文」；
    - 非成功 corpus_fetch 结果或不可解析时返回 ``None``（交回调用方按原策略处理）。
    """
    if budget <= 0 or not isinstance(body, str):
        return None
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    if len(body) <= budget:
        return body

    if "items" in payload:  # A2 分页信封：正文在 items，绝不能按单块结果压缩
        compact_envelope = _compact_envelope(payload)
        if len(compact_envelope) <= budget:
            return compact_envelope
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "budget_exceeded：本页正文（items）超过本轮工具结果预算；"
                    "为避免截断出非法 JSON 或丢掉正文，未返回本页。"
                    "请减少 locators 数量或提高本轮工具结果预算后重试。"
                ),
                "doc_id": payload.get("doc_id"),
                "build_id": payload.get("build_id"),
                "scope_id": payload.get("scope_id"),
                "next_cursor": payload.get("next_cursor"),
                "item_errors": payload.get("item_errors") or [],
                "unresolved": payload.get("unresolved") or [],
                "items": len(payload.get("items") or []),
                "text_chars": sum(
                    len(str(item.get("text") or ""))
                    for item in (payload.get("items") or [])
                    if isinstance(item, dict)
                ),
                "budget": budget,
            },
            ensure_ascii=False,
        )

    compact = _compact_payload(payload)
    compact["diagnostics_elided"] = True
    compact_json = json.dumps(compact, ensure_ascii=False)
    if len(compact_json) <= budget:
        return compact_json

    return json.dumps(
        {
            "ok": False,
            "error": (
                "budget_exceeded：该块正文超过本轮工具结果预算；为避免伪造完整，"
                '未截断正文。请改用 view="compact" 复取，或用更小的 locator 缩小范围。'
            ),
            "doc_id": payload.get("doc_id"),
            "locator": payload.get("locator"),
            "kind": payload.get("kind"),
            "build_id": payload.get("build_id"),
            "text_chars": len(payload.get("text") or ""),
            "budget": budget,
        },
        ensure_ascii=False,
    )


def _full_payload(
    doc_id: str,
    locator: str,
    evidence: Any,
    semantic_cells: Any,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "view": "full",
        "doc_id": doc_id,
        "locator": locator,
        "kind": evidence.kind,
        "build_id": evidence.build_id,
        "text": evidence.text,
        # 每个单元在**本 text** 内的偏移 (unit_id, start, end)：切片可复算出 text
        "spans": [
            {"unit_id": unit_id, "start": start, "end": end}
            for unit_id, start, end in evidence.spans
        ],
        # 权威原文 code point 区间（§4.2，来自 corpus_chunks.source_ranges）
        "source_ranges": [list(span) for span in evidence.source_ranges],
        "hint": _FULL_HINT,
    }
    if extra:  # A3：content_role／relations／relation_status（正文与控制字段之后、诊断之前）
        payload.update(extra)
    # ── 诊断 / 结构元数据（体积较大，置于正文与控制字段之后）──
    payload.update(
        {
            "source_id": evidence.source_id,
            "chunk_id": evidence.chunk_id,
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
        }
    )
    return payload


def _page(
    doc_id: str,
    request: list[str],
    view: str,
    max_chars: int,
    member_index: int,
    offset: int,
    unresolved_in: list[str],
) -> str:
    """A2.2 一致的分页信封：逐成员取回、超限分片、失败进 ``item_errors``／``unresolved``。"""
    from plugins.corpus.preparation import read_pg

    try:
        build_id = read_pg.parse_build_handle(doc_id)
    except Exception as exc:
        return _json_error(f"取证失败（句柄不可解析）：{exc}")

    svc = get_service()
    scope_id = context_scope_id(build_id, tuple(request))
    items: list[dict[str, Any]] = []
    item_errors: list[dict[str, Any]] = []
    unresolved = list(dict.fromkeys(unresolved_in))

    # A3：关联在**整个请求范围**上算一次（与清单同口径），逐页稳定；读取失败则退回仅角色。
    relation_fields = svc.context_relations(doc_id, request)

    def relation_extra(locator: str, kind: str) -> dict[str, Any]:
        found = relation_fields.get(locator)
        if found is not None:
            return found
        return {
            "content_role": content_role_for_kind(kind),
            "relations": [],
            "relation_status": "unknown",
        }

    def envelope(
        items_: list[dict[str, Any]],
        next_cursor: str | None,
        exhausted: bool,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "schema_version": _SCHEMA_VERSION,
            "cursor_type": CONTENT,
            "doc_id": doc_id,
            "build_id": build_id,
            "scope_id": scope_id,
            "view": view,
            "items": items_,
            "item_errors": item_errors,
            "unresolved": unresolved,
            "next_cursor": next_cursor,
            "exhausted": exhausted,
            "fetch_complete": exhausted and not unresolved and not item_errors,
            "page_id": _page_id(scope_id, member_index, offset, max_chars),
            "hint": _PAGE_HINT,
        }

    if len(json.dumps(envelope([], None, False), ensure_ascii=False)) + _MARGIN > max_chars:
        return _json_error(
            "budget_exceeded：本次 max_chars 连分页信封都装不下；请提高 max_chars",
            doc_id=doc_id,
            scope_id=scope_id,
        )

    mi = member_index
    off = offset
    while mi < len(request):
        locator = request[mi]
        try:
            evidence = svc.fetch_verbatim(doc_id, locator)
        except Exception as exc:
            item_errors.append({"locator": locator, "code": _error_code(exc), "error": str(exc)})
            if locator not in unresolved:
                unresolved.append(locator)
            mi += 1
            off = 0
            continue
        text = evidence.text
        if off >= len(text):
            mi += 1
            off = 0
            continue
        status = _evidence_structure_status(svc, evidence)
        extra = relation_extra(locator, evidence.kind)
        # D3：固定字段本身可能撑爆预算，而 full 视图的 units 单元清单正是体积大头。
        # 此处按需**自动改用 compact 视图重试一次**（去掉该清单），对调用方透明——一次
        # 请求就能取回正文，调用方不必自己领悟「pytest 改 view=compact」。游标仍绑定
        # 页面视图，续取时同一成员会再次走同样的回退，故无需改游标 schema。
        # 片段文本预算从「空正文 item + 真实游标」的实测信封反推，连同 units 键开销与
        # 游标长度一起计入，避免控制字段撑爆实际预算。
        tried_views = ["compact"] if view == "compact" else [view, "compact"]
        member_view = view
        fragment_budget = 0
        for candidate in tried_views:
            empty_item = _item(evidence, locator, 0, 0, candidate, status, extra)
            probe_len = len(
                json.dumps(
                    envelope(
                        [empty_item],
                        _content_cursor(doc_id, build_id, request, view, mi, off, unresolved),
                        False,
                    ),
                    ensure_ascii=False,
                )
            )
            fragment_budget = max_chars - probe_len - _MARGIN
            if fragment_budget > 0:
                member_view = candidate
                break
        if fragment_budget <= 0:
            item_errors.append(
                {
                    "locator": locator,
                    "code": "budget_exceeded",
                    "error": (
                        "该块的固定字段（单元清单／游标）已占满本次 max_chars，"
                        f"自动改用 compact 视图后仍装不下（已尝试 {tried_views}）；"
                        f"请提高 max_chars（当前 {max_chars}）后重试本 locator。"
                    ),
                    "views_tried": tried_views,
                }
            )
            if locator not in unresolved:
                unresolved.append(locator)
            mi += 1
            off = 0
            continue
        item_extra = dict(extra)
        if member_view != view:  # 回退对调用方透明，但如实标注在 item 上供审计
            item_extra["view_fallback"] = member_view
        try:
            ranges = _fragment_ranges(text, evidence.kind, fragment_budget, off)
        except _AtomTooLarge as exc:
            item_errors.append(
                {
                    "locator": locator,
                    "code": "unit_too_large",
                    "error": (
                        f"最小原子单元 {exc.chars} 字符超过本片段预算 {fragment_budget}；"
                        "请提高 max_chars，或改用专门单元读取；本轮不宣称已取全"
                    ),
                    "needed_chars": exc.chars,
                }
            )
            if locator not in unresolved:
                unresolved.append(locator)
            mi += 1
            off = 0
            continue
        for frag_start, frag_end in ranges:
            item = _item(
                evidence,
                locator,
                frag_start,
                frag_end,
                member_view,
                status,
                item_extra,
            )
            if items:
                probe = json.dumps(
                    envelope(
                        [*items, item],
                        _content_cursor(
                            doc_id, build_id, request, view, mi, frag_start, unresolved
                        ),
                        False,
                    ),
                    ensure_ascii=False,
                )
                if len(probe) > max_chars:
                    next_cursor = _content_cursor(
                        doc_id, build_id, request, view, mi, frag_start, unresolved
                    )
                    return json.dumps(envelope(items, next_cursor, False), ensure_ascii=False)
            items.append(item)
        mi += 1
        off = 0

    return json.dumps(envelope(items, None, True), ensure_ascii=False)


@tool
async def corpus_fetch(
    doc_id: str,
    locator: str | None = None,
    locators: list[str] | None = None,
    cursor: str | None = None,
    view: str = "full",
    max_chars: int = 6000,
) -> str:
    """取回语料中指定块的逐字原文，用于写入 ``evidence.quote``。

    在 ``corpus_search`` 之后调用：search 给句柄，本工具给原文。单块结果装得下时
    维持既有单块字段语义；批量／游标模式返回一致的分页信封；单块超限自动分片。

    Args:
        doc_id: 版本句柄（来自 ``corpus_search`` 的 ``doc_id``，形如 ``cv2:<build_id>``）。
        locator: 单块句柄（来自 ``corpus_search`` 的 ``locator``，形如 ``chunk:<chunk_id>``）。
        locators: 批量块句柄（有序，按首次出现去重）；表格块请附带必要表头、期间、单位。
        cursor: 续取游标（上一页返回的 ``next_cursor``；类型必须为 ``content``）；
            游标已绑定请求集合、顺序、视图与位置，续取时不得改动，视图由游标决定。
        view: 返回视图。``"full"``（默认）保留完整诊断／结构元数据；``"compact"``
            只保留正文、引用最小映射、单元身份与结构状态，并给出可取回完整元数据的
            可解析引用（``meta_ref``）。取值非法时返回 ``ok=false``，不静默兼容。
            游标模式下忽略本参数（以游标绑定的视图为准）。
        max_chars: 本页序列化 JSON 的字符上限；服务按实际运行路径收紧。
            ``locator``、``locators``、``cursor`` 三者**恰选其一**。

    Returns:
        单块（``locator``）装得下时返回既有单块形状 ``{"ok": true, "view", "doc_id",
        "locator", "kind", "build_id", "text", "spans", "source_ranges", "hint",
        "content_role", "relations", "relation_status", ...}``；
        批量／游标或单块超限时返回分页信封 ``{"ok": true, "schema_version",
        "cursor_type": "content", "doc_id", "build_id", "scope_id", "view", "items",
        "item_errors", "next_cursor", "exhausted", "fetch_complete", "unresolved",
        "page_id", "hint"}``。每个 item 亦带 ``content_role``（标题块为
        ``heading_only``）与 ``relations``（本次请求范围内的结构关联，``verified`` 与
        ``candidate`` 严格分开）。旧句柄／来源已撤销／游标类型不符时返回 ``ok=false``。
    """
    if not isinstance(doc_id, str) or not doc_id.strip():
        return _json_error("doc_id 必须是非空字符串")

    # I2-8：旧句柄（无 cv2: 前缀）不得拿新链正文顶替——显式 archive_required。
    if not doc_id.startswith("cv2:"):
        return _json_error(
            "archive_required：该 doc_id 是旧句柄（非 cv2:<build_id>），"
            "新链不以其取正文，也不以新版本冒称旧引用；"
            "历史引用请走已归档副本解释，或重新检索取得当前版本句柄。",
            doc_id=doc_id,
            locator=locator if isinstance(locator, str) else None,
        )

    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < _MIN_BUDGET:
        return _json_error(
            f"max_chars 必须是 ≥ {_MIN_BUDGET} 的整数（收到 {max_chars!r}）；"
            "预算过小则连分页信封都装不下",
        )

    given = [locator is not None, locators is not None, cursor is not None]
    if sum(given) != 1:
        return _json_error(
            "locator、locators、cursor 三者恰选其一（不得同时给出或同时省略）",
            doc_id=doc_id,
        )

    # ── 游标模式：视图、请求集合与起点都由游标决定（A2.2） ──
    if cursor is not None:
        try:
            payload = decode_cursor(cursor)
        except CursorError as exc:
            return _json_error(f"游标不可用：{exc}", cursor_type=CONTENT)
        if payload.get("type") != CONTENT:
            return _json_error(
                f"游标类型不符：该游标是 {payload.get('type')!r}，本工具只接受 {CONTENT!r}",
                cursor_type=CONTENT,
            )
        if payload.get("doc_id") != doc_id:
            return _json_error(
                "游标绑定的 doc_id 与本次调用不一致；续取不得切换文档/版本",
                cursor_type=CONTENT,
            )
        request = [str(item) for item in (payload.get("req") or [])]
        if not request:
            return _json_error("游标未绑定任何请求集合（损坏）", cursor_type=CONTENT)
        return _page(
            doc_id,
            request,
            str(payload.get("view") or "full"),
            max_chars,
            int(payload.get("mi") or 0),
            int(payload.get("off") or 0),
            [str(item) for item in (payload.get("unresolved") or [])],
        )

    # ── 批量模式：一致的分页信封 ──
    if locators is not None:
        try:
            request = _dedupe_locators(list(locators))
        except ValueError as exc:
            return _json_error(str(exc))
        if not request:
            return _json_error("locators 不能为空列表")
        return _page(doc_id, request, view, max_chars, 0, 0, [])

    # ── 单块模式：装得下即维持既有单块形状 ──
    if not isinstance(locator, str) or not locator.strip():
        return _json_error("locator 必须是非空字符串")

    # A0.2：未知视图显式拒绝（fail-closed），不静默退回 full 也不猜。
    if view not in _VALID_VIEWS:
        return _json_error(
            f"view 必须是 {_VALID_VIEWS} 之一，收到 {view!r}",
            doc_id=doc_id,
            locator=locator,
            view=view if isinstance(view, str) else None,
        )

    try:
        svc = get_service()
        evidence = svc.fetch_verbatim(doc_id, locator)
        semantic_cells = svc.emit_cells(evidence)
    except Exception as exc:
        return _json_error(f"取证失败（句柄不可解析、跨 build 或来源已撤销）：{exc}")

    # A0.1 正文优先：字段顺序按「身份 → 正文 → 引用映射/控制字段 → 诊断元数据」
    # 排列，任何 head-only 截断下模型都先见到 text 与续取所需控制字段，体积较大的
    # 诊断元数据（units/semantic_cells）置于其后。字段与语义保持不变。
    # A3：单块请求范围只有本块，故无同范围关联；content_role 仍按块种类给出。
    extra = {
        "content_role": content_role_for_kind(evidence.kind),
        "relations": [],
        "relation_status": "unknown",
    }
    full = _full_payload(doc_id, locator, evidence, semantic_cells, extra)
    body = json.dumps(_compact_payload(full) if view == "compact" else full, ensure_ascii=False)
    if len(body) <= max_chars:
        return body

    # 单块超限：显式分片为信封，不悄悄改写为「已取得全文」。
    return _page(doc_id, [locator], view, max_chars, 0, 0, [])
