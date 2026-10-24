"""corpus_search — 定位并交付有界原文证据；缺失上下文由 corpus_fetch 补读。

原生命中的 evidence_spans 只标记经原文校验的完整节选。实际送达后可逐字引用，
仍由账本核对范围、resolver 核对来源；无标记的旧 snippet 和预览不获得引用资格。
"""

from __future__ import annotations

import json
import os
from typing import Any

from frontier_agent.core.tool import tool
from plugins.corpus.search_evidence import SEARCH_EVIDENCE_CONTRACT, search_evidence_items
from plugins.corpus.search_refs import CONTRACT as REFERENCE_CONTRACT
from plugins.corpus.search_refs import SearchReferenceError, compact_hit
from plugins.corpus.service import get_service

MAX_LIMIT = 20

# CORPUS_EVIDENCE_PREVIEW=pilot adds sentence previews and core read plans only
# in the isolated database. Previews never register as fetched/delivered evidence.

#: 超预算压缩时逐命中保留的核心字段（模型据此定位并复取，缺一不可）。
_HIT_CORE_KEYS = (
    "doc_id",
    "locator",
    "source_id",
    "build_id",
    "chunk_id",
    "scope_id",
    "context_locators",
    "fetch_plan",
    "core_fetch_plan",
    "evidence_contract",
    "evidence_spans",
    "excerpts",
    "scope_ref",
    "available_blocks",
)
#: 核心字段之外按预算余量保留的可选字段（顺序即保留优先级）。
_HIT_OPTIONAL_KEYS = ("title", "published", "snippet", "by_kind", "preview")

#: 命中被按预算整条舍弃时替换的提示（明确后续动作，不让模型以为检索已取全）。
_ELIDED_HINT = (
    "本次命中数超过工具结果预算，已按相关度**整条**舍弃尾部命中"
    "（舍弃条数见 hits_elided，最相关的若干条仍完整保留）。"
    "snippet 已截断，仅用于定位，禁止直接引用；"
    "写 evidence 前请用 corpus_fetch(doc_id, locator) 取回逐字原文，"
    "并依次取回 context_locators。需要看全被舍弃的命中时，"
    "请用更具体的 query 或更小的 limit 重新检索。"
)

#: 无研报覆盖时的**流程级指令**（不是建议，是要求）。
#:
#: 关键点：语料里没有相关研报时，必须让模型**立刻停下「继续找研报」这条路**
#: （否则它会反复检索，或去够一篇沾边但不相关的研报凑 evidence），
#: 转而走市场数据 + 技术面。同时钉住纪律：禁止编造研报、指标数值不得由模型自算。
NO_COVERAGE_HINT = (
    "当前已发布范围内没有与该查询匹配的研报（query_status=no_match；"
    "availability=unknown——只说明该范围无匹配，不等于资料不存在）。"
    "**请立即停止继续检索研报，不要反复重试本工具**，切换到市场数据路径："
    "① 用 market_resolve 把标的消歧成 thscode（数据端点不接受纯代码）；"
    "② 用 market_quote 取实时行情与估值（价格实时变化，务必带 as_of 时点）；"
    "③ 用 market_history 取历史序列，做区间 / 均线 / 波动等技术面分析。"
    "纪律：禁止编造或引用不存在的研报；"
    "技术指标的**数值**必须来自确定性工具并带 computed_by，不得由你自行计算（硬闸②）；"
    "最终结论请明确标注『无研报覆盖，结论基于市场数据与技术面』，"
    "并在 evidence 中如实反映数据来源（市场接口而非研报）。"
)


#: B2 abstain 拒检的分流提示：有检索候选但判定为无实质答案而过拒检（与
#: ``no_match``「无研报覆盖」机器可区分）。同样是流程级指令：不许编造研报、不重试。
ABSTAIN_HINT = (
    "查询命中候选，但判定为**无实质答案**（query_status=abstain；availability=unknown"
    "——只说明判为拒检，不等于资料不存在）。**请立即停止继续检索研报，不要反复重试本工具**，"
    "切换市场数据路径并明确标注『无研报覆盖，结论基于市场数据与技术面』："
    "① 用 market_resolve 消歧；② 用 market_quote 取实时行情；③ 用 market_history 取历史序列。"
    "纪律：禁止编造或引用不存在的研报；最终结论不得凭空给出研报级数字。"
)


#: 每次结果只提示当前动作；固定坐标、范围及分页规则放在工具定义中。
NATIVE_HINT = (
    "仅 evidence_spans 标记的原文可引用，句柄用 context_locators[member-1]。"
    "证据足够时无需重复 fetch；缺上下文时按需补读。未标记文本仅供定位。"
)
NATIVE_PREVIEW_HINT = "本次仅返回定位预览，无可直接引用的原文区间；请按原句柄 fetch 补读。"
REFERENCE_HINT = (
    "excerpts 原文可引用，使用同一 doc_id 和 ref 作为 locator。缺上下文时 fetch 补读；"
    "其他候选用 scope_ref 调用 corpus_inventory。preview 不可引用。"
)


def _native_delivery(hits: list[dict[str, Any]]) -> dict[str, int]:
    """Count only intact evidence in this message, never the unshown candidate text."""
    characters = 0
    blocks: set[tuple[str, str]] = set()
    for hit in hits:
        for item in search_evidence_items(hit):
            characters += len(item["text"])
            blocks.add((hit["doc_id"], item["locator"]))
    return {"evidence_characters": characters, "evidence_blocks": len(blocks)}


def _native_hint(delivery: dict[str, int], elided: int = 0, *, references: bool = False) -> str:
    hint = NATIVE_HINT if delivery["evidence_blocks"] else NATIVE_PREVIEW_HINT
    if references:
        hint = (
            REFERENCE_HINT
            if delivery["evidence_blocks"]
            else ("本次仅有定位预览；用 scope_ref 调用 corpus_inventory 选择候选，再 fetch 补读。")
        )
    return ("尾部命中因预算被整条省略。" if elided else "") + hint


@tool
async def corpus_search(query: str, limit: int = 10) -> str:
    """检索研报，返回定位句柄及有界原文；缺失上下文用 corpus_fetch 补读。

    原生 v2 命中 evidence_contract=native-search-evidence-v2 的 excerpts 是原文证据，
    每项含 text 和 ref。引用时使用同一命中的 doc_id，以 ref 原样作为 evidence.locator
    （或 evidence.page）；补读使用 corpus_fetch(doc_id, locator=ref, view="compact")，
    返回该片段所属整块，超预算时分页。不得自行解析、拼接或扩写短引用。
    available_blocks 是原候选范围块数，不是已读数；用 corpus_inventory(doc_id,
    scope_ref=scope_ref) 展开其他候选，再按需 fetch。完整校验记录保存在后台，
    引用丢失/损坏/跨版本时显式失败，需重新检索；持有 ref 不代表原文已送达。
    preview 只用于定位，不可引用。excerpts 充分时无需重复 fetch，缺条件时必须补读。

    历史 v1 命中 evidence_contract=native-search-evidence-v1 的 evidence_spans 标记
    snippet 中可逐字引用的原文区间；实际送达且足以支撑结论时无需例行 fetch。
    引用使用同一命中的 doc_id 与 context_locators[span.member-1]。未标记文本、
    旧 snippet、索引说明和句内节选仅供定位。缺条件、指代、表格依赖或更多原文时，
    用原句柄 corpus_fetch(view="compact") 补读；节选完整不代表全篇已读或结论充分。

    坐标规则：所有偏移按解码后的 Unicode 字符计，零基、左闭右开。
    snippet_start:snippet_end 是展示区间，start:end 是 fetch 块内区间。
    【i/N】中的 i 是 context_locators 的一基成员号，不是展示顺序；不同节选不连续。
    不得混用版本、扩写句柄或一律引用命中首 locator。补读按需选择成员，
    不必默认申请整个数组；分页按 next_cursor 续读，未读完不声称申请范围完整。

    数量规则：原生结果 count 是本次返回命中数；预算省略时 hits_total 是省略前
    命中数，hits_elided 是省略数。delivery.evidence_characters / evidence_blocks
    仅统计本消息中可核验的原文字符 / 不同块数，不含标签、预览和未展示正文，
    不代表结论充分；被压成摘要的文本不自动取得原文证据资格。
    coverage.native.body_characters / blocks_returned 是预算裁剪前合并的候选正文
    字符 / 块数，blocks_ranked 是排序候选数，都不等于已交付正文。
    title 是首命中块标题，未必是报告名称。结果只覆盖允许的原生正文；
    未展示不等于不存在，未合并的候选需继续检索，未命中不等于全库无资料。

    Args:
        query: 检索词。可以是关键词、数字（如 ``47.3亿``、``30%``）
            或一句话；数字与其单位会被整体匹配。
        limit: 返回条数上限，默认 10。

    Returns:
        原生 v2：``{"ok": true, "hits": [{"doc_id", "title", "published",
        "excerpts": [{"text", "ref"}], "scope_ref", "available_blocks",
        "evidence_contract", "preview"?}], "coverage": {...}, "delivery": {...}, "hint": ...}``。
        存储不可用时返回自包含 v1（snippet/evidence_spans/context_locators），
        标记 reference_storage=unavailable_v1_fallback。旧检索保持原定位结构。
        doc_id 仍为 cv2:<build_id>，短引用不能更改版本；coverage 为 §7.3 三轴对象。
        语料库不存在时返回 ``ok=false``。结果超过本轮工具结果预算时不会按字符硬切
        （那样会破坏 JSON 与句柄），而是整条舍弃尾部命中并标 ``hits_elided``、
        去掉可推导字段并标 ``diagnostics_elided``；连一条都装不下时返回
        ``ok=false`` 的预算错误，提示缩小 query 或 limit。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "error": "query 必须是非空字符串", "hits": []},
            ensure_ascii=False,
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        limit = 10
    limit = min(limit, MAX_LIMIT)

    coverage: dict | None = None
    try:
        svc = get_service()
        # §7.3：命中与覆盖元数据必须取自同一数据库快照（RM-I28-3）；
        # Service 提供组合读取时一次取回，避免拼接两个时刻的状态。
        if hasattr(svc, "search_with_coverage"):
            hits, coverage = svc.search_with_coverage(query, limit=limit)
        else:
            hits = svc.search(query, limit=limit)
    except Exception as exc:  # 库不可用 / 连接失败 / 检索异常统一归到 ok=false
        return json.dumps(
            {
                "ok": False,
                "error": f"检索失败（语料库可能未就绪）：{exc}",
                "hits": [],
            },
            ensure_ascii=False,
        )

    status = "matched" if hits else "no_match"
    if coverage is None:
        try:
            coverage = svc.coverage(query_status=status)
        except Exception:  # 覆盖统计不可读不影响主流程，但必须显式为 unknown
            coverage = {
                "processing": "unknown",
                "query_status": status,
                "availability": "unknown",
                "reason_codes": ("coverage_unavailable",),
            }

    if not hits:
        # 「没有相关研报」与「检索成功但为空」此前长得一样（ok=true + 空 hits），
        # 模型无法区分，容易硬凑。这里给出**显式覆盖度信号 + 明确的下一步**。
        # I2-8：空命中按 §7.3 表述为"该已查询范围无匹配"，不给 availability=absent。
        # B2：被 abstain 拒检（有检索候选但无实质答案）与 no_match（无研报覆盖）
        # 机器可区分——coverage["abstain"] 为真时走 ABSTAIN_HINT 并置顶层 abstain。
        if coverage.get("abstain"):
            return json.dumps(
                {
                    "ok": True,
                    "query": query,
                    "count": 0,
                    "hits": [],
                    "coverage": coverage,
                    "abstain": True,
                    "hint": ABSTAIN_HINT,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "ok": True,
                "query": query,
                "count": 0,
                "hits": [],
                "coverage": coverage,
                "hint": (
                    "本次候选经相关性与结构筛选后未获得可展示正文，不代表资料库无答案。"
                    "可改写或拆分查询继续检索；已有句柄仍可按原范围 fetch。"
                    if coverage.get("purity", {}).get("sources_filtered")
                    else NO_COVERAGE_HINT
                ),
            },
            ensure_ascii=False,
        )
    native = bool(coverage.get("native"))
    payload_hits = []
    for hit in hits:
        # I2-8 §7.2 版本句柄：doc_id=cv2:<build_id>、locator=chunk:<chunk_id>
        head = {
            "doc_id": hit.doc_id,
            "locator": hit.locator,
            "source_id": hit.source_id,
            "build_id": hit.build_id,
            "chunk_id": hit.chunk_id,
            "context_locators": list(hit.context_locators),
        }
        # fetch_plan 把文档句柄与上下文范围组成一个不可拆的复取计划，避免调用方
        # 从不同命中拼接 doc_id 与 locator。原生检索的 context_locators 已经与
        # doc_id 同属一条命中，再写一份完全相同的 locator 数组只会重复占用预算，
        # 因此该路径只保留一份句柄数组；调用方用同一命中的 doc_id + context_locators。
        plan = (
            {}
            if native
            else {
                "fetch_plan": {
                    "doc_id": hit.doc_id,
                    "locator": hit.locator,
                    "locators": list(hit.context_locators),
                    "scope_id": hit.scope_id,
                    "view": "compact",
                }
            }
        )
        # A1 内联 scope 摘要：成员范围身份 + 按 kind 计数 + 表块数。
        # 只报告**块**统计，不声称「共有几张表」（表身份未知时为 null）。
        payload_hits.append(
            {
                "title": hit.title,
                "published": hit.published,
                "snippet": hit.snippet,
                **(
                    {
                        "evidence_contract": SEARCH_EVIDENCE_CONTRACT,
                        "evidence_spans": list(hit.evidence_spans),
                    }
                    if native and getattr(hit, "evidence_spans", ())
                    else {}
                ),
                **head,
                **plan,
                "scope_id": hit.scope_id,
                "total_chunks": len(hit.context_locators),
                "by_kind": dict(hit.context_by_kind),
                "table_chunks": dict(hit.context_by_kind).get("table", 0),
            }
        )
    reference_storage_failed = False
    if native:
        try:
            payload_hits = [compact_hit(hit) for hit in payload_hits]
        except (OSError, SearchReferenceError):
            # Retain the complete self-contained v1 result if durable storage is
            # unavailable; never issue references that only this process can read.
            reference_storage_failed = True
    references = native and not reference_storage_failed
    delivery = _native_delivery(payload_hits) if native else {}
    body = json.dumps(
        {
            "ok": True,
            "query": query,
            "count": len(hits),
            "hits": payload_hits,
            **({"delivery": delivery} if native else {}),
            **(
                {"reference_storage": "unavailable_v1_fallback"} if reference_storage_failed else {}
            ),
            "coverage": coverage,
            # hint 显式告诉模型下一步该做什么，而不是让它自己领会
            "hint": (
                _native_hint(delivery, references=references)
                if native
                else (
                    "snippet 已截断，仅用于定位，禁止直接引用。"
                    "写 evidence 前请严格使用同一命中的 fetch_plan.doc_id 与"
                    "fetch_plan.locators 和 fetch_plan.view 调用 corpus_fetch；不得把不同命中的 doc_id、"
                    "locator 或 context_locators 混在一起。这些句柄共同构成有界的文档证据区。"
                    "需要先看清这批上下文候选的结构（哪些是标题、哪些是表格块、"
                    "各自覆盖哪些页与区间）时，用 corpus_inventory(doc_id, locators=context_locators)。"
                )
            ),
        },
        ensure_ascii=False,
        separators=(",", ":") if native else None,
    )
    if native:
        return body
    if os.environ.get("CORPUS_EVIDENCE_PREVIEW", "off") == "pilot":
        payload = json.loads(body)
        try:
            views = svc.evidence_previews(query, hits)
            if len(views) != len(hits):
                raise ValueError("preview_count_mismatch")
            for row, view in zip(payload["hits"], views, strict=True):
                row.update(view)
            payload["delivery_preview"] = "pilot"
            payload["hint"] = (
                "preview 是选读预览，不是已取证引用。先用同一命中的 core_fetch_plan 调用 "
                "corpus_fetch；问题涉及多个对象、因果链或指代不完整时，再按 fetch_plan "
                "扩展上下文。表格保留原范围以带齐表头、期间和单位。"
                "重复 locator 可在相同 doc_id 下去重；不同版本不可混用。"
            )
        except Exception as exc:
            # Preview reads can race retraction; never expose a partial preview batch.
            # Original handles remain subject to the normal fetch revocation checks.
            payload = json.loads(body)
            payload["delivery_preview"] = "unavailable"
            payload["delivery_preview_error"] = type(exc).__name__
        return json.dumps(payload, ensure_ascii=False)
    return body


def _compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """逐命中只保留定位与复取必需字段（其余为可推导／诊断字段）。"""
    out = {}
    for key in _HIT_OPTIONAL_KEYS:
        if key in hit:
            out[key] = hit[key]
    out.update({key: hit[key] for key in _HIT_CORE_KEYS if key in hit})
    return out


def fit_search_payload(body: str, budget: int) -> str | None:
    """A0.3：把 ``corpus_search`` 的结构化 JSON 结果压进 ``budget``，始终返回**合法 JSON**。

    与 ``corpus_fetch.fit_structured_payload`` 同一契约，策略按搜索结果的语义定：
    命中按相关度排序，**整条命中**才是「一篇可去读的文档」这一原子单位，所以逐级
    降级但绝不切开单条命中的 ``context_locators``——那是本次请求的取证范围，切开会让
    「有界证据区」的承诺与账本的 offered 集合同时失真；也不按字符硬切（会同时破坏
    JSON 与句柄）。降级阶梯：

    1. ≤ ``budget``：原样返回，不改任何字段；
    2. 超预算：逐命中只保留定位与复取必需字段（其余可推导／诊断字段去掉），装下即返回，
       并标 ``diagnostics_elided``；
    3. 仍超：按相关度从**尾部整条**舍弃命中（至少保留 1 条），标 ``hits_elided``；
    4. 连 1 条都装不下：返回可识别的**预算错误**（仍为合法 JSON），不返回残缺正文。

    非成功结果或不可解析时返回 ``None``（交回调用方按原策略处理）。
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
    native = bool((payload.get("coverage") or {}).get("native"))
    references = any(
        hit.get("evidence_contract") == REFERENCE_CONTRACT for hit in payload.get("hits", [])
    )
    if native:
        # Preserve each complete native scope without duplicating its locator
        # array in fetch_plan and context_locators under a small message budget.
        for hit in payload.get("hits", []):
            hit.pop("fetch_plan", None)
        payload["delivery"] = _native_delivery(payload.get("hits", []))
        payload["hint"] = _native_hint(
            payload["delivery"], payload.get("hits_elided", 0), references=references
        )
        payload["plans_compacted"] = True
        candidate = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(candidate) <= budget:
            return candidate
    # The full plan duplicates doc_id/context_locators. In the pilot compact
    # representation preserve those handles and core plan; do not spend the
    # budget twice on identical locator arrays before showing readable text.
    if payload.get("delivery_preview") == "pilot":
        for hit in payload.get("hits", []):
            hit.pop("expansion", None)
            hit.pop("delivery_hint", None)
            hit.pop("fetch_plan", None)
        payload["hint"] = (
            "preview 仅供选读，不是引用证据。先用 core_fetch_plan 调用 corpus_fetch；"
            "需要扩展时用同一命中的 doc_id 和完整 context_locators，view=compact。"
            "多个对象、因果链或指代不完整时应扩展。不同版本不可混用。"
        )
        payload["plans_compacted"] = True
        compact = json.dumps(payload, ensure_ascii=False)
        if len(compact) <= budget:
            return compact

    hits = [hit for hit in (payload.get("hits") or []) if isinstance(hit, dict)]
    if not hits:
        return None

    compact_hits = [_compact_hit(hit) for hit in hits]
    if native:
        for hit in compact_hits:
            # 只删可由 context_locators 推导的统计；title/published 是主体与时点，
            # snippet 是这条命中唯一的正文，二者都不再按字符截断——装不下就整条让位，
            # 避免"每条截到 120 字"把不同长度的正文压成同样不可用的残句。
            hit.pop("by_kind", None)

    def render(keep: list[dict[str, Any]]) -> str:
        out: dict[str, Any] = {
            "ok": True,
            "query": payload.get("query"),
            "count": payload.get("count", len(hits)),
            "hits": keep,
            "coverage": payload.get("coverage"),
            "hint": payload.get("hint"),
            "diagnostics_elided": True,
        }
        if payload.get("delivery_preview") == "pilot":
            out["delivery_preview"] = "pilot"
            out["plans_compacted"] = True
            if any("preview" not in hit for hit in keep):
                out["previews_elided"] = True
        if native:
            out["plans_compacted"] = True
            out["count"] = len(keep)
            out["delivery"] = _native_delivery(keep)
            elided = payload.get("hits_elided", 0) + len(hits) - len(keep)
            out["hint"] = _native_hint(out["delivery"], elided, references=references)
            if elided:
                out["hits_total"] = len(keep) + elided
                out["hits_elided"] = elided
        if not native and len(keep) < len(hits):
            out["hits_elided"] = len(hits) - len(keep)
            out["hint"] = (
                "尾部命中因预算被整条省略。" + str(payload["hint"])
                if payload.get("delivery_preview") == "pilot"
                else _ELIDED_HINT
            )
        return json.dumps(out, ensure_ascii=False, separators=(",", ":") if native else None)

    candidate = render(compact_hits)
    if len(candidate) <= budget:
        return candidate

    for keep in range(len(compact_hits) - 1, 0, -1):
        candidate = render(compact_hits[:keep])
        if len(candidate) <= budget:
            return candidate

    # If even one complete hit with its preview cannot fit, discard only that
    # optional text before emitting a budget error; never clip a sentence/scope.
    if payload.get("delivery_preview") == "pilot":
        for hit in compact_hits:
            hit.pop("preview", None)
        for keep in range(len(compact_hits), 0, -1):
            candidate = render(compact_hits[:keep])
            if len(candidate) <= budget:
                return candidate

    return json.dumps(
        {
            "ok": False,
            "error": (
                "budget_exceeded：本次检索命中的定位句柄超过本轮工具结果预算；"
                "为避免截断出非法 JSON 或丢掉取证范围，未返回命中。"
                "请用更具体的 query 或更小的 limit 重新检索。"
            ),
            "query": payload.get("query"),
            "hits_total": len(hits),
            "budget": budget,
        },
        ensure_ascii=False,
    )
