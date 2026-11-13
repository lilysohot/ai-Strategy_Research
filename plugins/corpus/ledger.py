"""A4 消费账本与结论证据校验：offered／requested／fetched／delivered + 两类完整性。

为什么需要这一层：``corpus_search`` 提供上下文候选及有界原文，``corpus_fetch`` 补读原文，
但「检索提供了什么」与「模型最终看到了什么」之间隔着两层截断——工作流后处理
（``ReactToolResultPostProcessor``）与单轮聚合预算（``_overflow``）。全部落在
trajectory 里的全文，并不等于进入了**最终模型请求**。本模块把这条链路的四个
状态分辨清楚：

| 状态 | 来源 | 不能混同为 |
|---|---|---|
| ``offered`` | 检索提供的完整候选范围 | 已被要求读取的范围 |
| ``requested`` | Agent 显式选定并请求的范围 | 已取回 |
| ``fetched`` | search 或 fetch 成功返回的已核验块／片段 | 已完整送达模型 |
| ``delivered`` | 最终消息里经后处理／聚合后**仍完整存在**的片段 | 已理解 |

两类完整性**分开算**：范围完整性（提供范围是否取回／送达）与结论证据充分性
（结论所需原文、期间、单位、表头、脚注是否齐备）。跳过记 ``skipped`` 仍使原范围
不完整；缩小范围要新建关联范围、不改分母。

结论证据清单的校验沿 [verify.py](verify.py) 的哲学：**不信任落盘字段**，由账本与
权威原文**重算**每条结论的状态，绝不接受模型自报的 ``complete=true``；缺清单的
产物只能标 ``draft``，不得标成「已通过证据完整性校验」。

观测模式（文档 §A4.2）：本模块只记录状态、不阻断运行。任何写盘／解析失败都
吞掉并记日志，绝不打断主流程。

落盘走 run artifacts 约定：``<APODEX_RUN_DIR>/corpus/ledger.json`` 与
``manifest_verification.json``；报告只引用 id，验证器读 JSON 重算。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frontier_agent.core.loop_types import (
    AgentLoopResult,
    BaseObserver,
    ToolResult,
    TurnContext,
)
from frontier_agent.core.messages import Message, text_of
from plugins.corpus import coverage, projection
from plugins.corpus.quote_match import find_quote_matches
from plugins.corpus.search_evidence import search_evidence_items
from plugins.corpus.search_refs import (
    SearchReferenceError,
    canonical_locator,
    offered_hit,
    resolve_scope_by_ref,
)
from plugins.corpus.structured.consumption import (
    SEMANTIC_TOOL,
    ReportSemanticReference,
    SemanticConsumption,
    verify_reference,
)

logger = logging.getLogger(__name__)

LEDGER_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 2
VERIFICATION_SCHEMA_VERSION = 2

# ── 四状态 + 补充词汇 ────────────────────────────────────────────────────
DELIVERED = "delivered"
TRUNCATED = "truncated"
UNKNOWN = "unknown"
SKIPPED = "skipped"

#: ``responses[].delivery_state`` 的两个消息边界失败态。它们与 ``failed``
#: （工具调用本身失败）分开：一个是"成功结果在消息边界被预算/投影替换"，
#: 一个是"cmeta 收据找不到或已损坏"。去重重投时必须能区分这三者。
BLOCKED_BY_BUDGET = "blocked_by_budget"
SNAPSHOT_UNRECOVERABLE = "snapshot_unrecoverable"

#: 同轮同参去重（single-flight）专用状态。``dedup_ref`` = 该调用没有真实执行，
#: 只有一条指向首份结果的简短关联回执，因此**不算一次送达**；只有首份的区间
#: 进入覆盖并集。``dedup_target_not_delivered`` = 首份在消息边界被判为未送达，
#: 关联回执随之失效，该请求仍须重新发起，绝不冒充已送达。
DEDUP_REF = "dedup_ref"
DEDUP_TARGET_NOT_DELIVERED = "dedup_target_not_delivered"

# 结论状态（结论证据充分性）
SUPPORTED = "supported"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"

# 产物发布状态（报告／最终回复）。``verification_error`` 与 ``draft`` 分开：
# 缺清单是确定性的「没有可校验对象」，基础设施故障是「校验本身不可信」——
# 两者都不得标成已校验，但排查动作完全不同（评审 C7）。
PUBLISH_VERIFIED = "verified"
PUBLISH_PARTIAL = "partial"
PUBLISH_UNSUPPORTED = "unsupported"
PUBLISH_DRAFT = "draft"
PUBLISH_VERIFICATION_ERROR = "verification_error"

#: 交付状态强弱（合并时取更强，绝不因某一路径看不到而降级）。
_DELIVERY_RANK = {UNKNOWN: 1, TRUNCATED: 2, DELIVERED: 3}

#: 结论证据覆盖（delivered 为最全，unknown 为无法核验）。
_EVIDENCE_RANK = {UNKNOWN: 0, "partial": 1, DELIVERED: 2}

TOOL_SEARCH = "corpus_search"
TOOL_FETCH = "corpus_fetch"
TOOL_INVENTORY = "corpus_inventory"
CORPUS_TOOLS = frozenset({TOOL_SEARCH, TOOL_FETCH, TOOL_INVENTORY, SEMANTIC_TOOL})

#: 声明依赖的用途词表（结论证据充分性按用途核对）。
DEPENDENCY_PURPOSES: tuple[str, ...] = (
    "value",
    "period",
    "unit",
    "header",
    "footnote",
    "condition",
    "negation",
    "attribution",
)

#: 判定「截断」所需的最短可辨前缀；片段太短则只记 unknown，不猜截断。
TRUNCATED_MIN_PREFIX = 32

#: run artifacts 相对路径（A4 落盘 = 独立 JSON 工件）。
_ARTIFACT_SUBDIR = "corpus"
LEDGER_FILENAME = "ledger.json"
MANIFEST_FILENAME = "manifest.json"
#: 子清单目录：各代理／各次提交独立落盘，绝不互相覆盖（评审 C4）；
#: 边界汇总时聚合全部候选，最终以验证工件为准。
MANIFESTS_SUBDIR = "manifests"
VERIFICATION_FILENAME = "manifest_verification.json"

_RUN_DIR_ENV = "APODEX_RUN_DIR"

#: 同一 run 共享的账本（子代理与主循环都往里追加）。
_LEDGERS: dict[str, ConsumptionLedger] = {}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _short_digest(text: str) -> str:
    """不透明游标/句柄的稳定短摘要：可对账，不可还原。"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _escaped(text: str) -> str:
    """把片段文本转成它在 JSON 字符串里出现的形式（去掉两侧引号）。"""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _merge_intervals(
    intervals: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _covers_whole(intervals: list[tuple[int, int]], chars: int) -> bool:
    """区间并集是否覆盖 ``[0, chars)``；长度未知（``chars<=0``）时一律 False。"""
    if chars <= 0:
        return False
    merged = _merge_intervals(intervals)
    return len(merged) == 1 and merged[0][0] == 0 and merged[0][1] >= chars


def _covers_interval(
    intervals: list[tuple[int, int]],
    start: int,
    end: int,
) -> bool:
    """区间并集是否覆盖连续区间 ``[start, end)``。"""
    if end <= start:
        return False
    return any(lo <= start and hi >= end for lo, hi in _merge_intervals(intervals))


def delivery_rank(status: str) -> int:
    return _DELIVERY_RANK.get(status, 1)


def evidence_rank(status: str) -> int:
    return _EVIDENCE_RANK.get(status, 0)


# ── 片段身份 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FragmentRef:
    """一个已取回片段的身份（不含正文；正文只存内存用于 delivered 核验）。"""

    doc_id: str
    build_id: str
    locator: str
    kind: str
    start: int
    end: int
    chars: int
    content_sha256: str
    fragment_sha256: str
    turn: int = 0

    @property
    def identity(self) -> tuple[str, str, int, int]:
        return (self.doc_id, self.locator, self.start, self.end)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "build_id": self.build_id,
            "locator": self.locator,
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "chars": self.chars,
            "content_sha256": self.content_sha256,
            "fragment_sha256": self.fragment_sha256,
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FragmentRef:
        return cls(
            doc_id=str(payload.get("doc_id") or ""),
            build_id=str(payload.get("build_id") or ""),
            locator=str(payload.get("locator") or ""),
            kind=str(payload.get("kind") or ""),
            start=int(payload.get("start") or 0),
            end=int(payload.get("end") or 0),
            chars=int(payload.get("chars") or 0),
            content_sha256=str(payload.get("content_sha256") or ""),
            fragment_sha256=str(payload.get("fragment_sha256") or ""),
            turn=int(payload.get("turn") or 0),
        )


def _offered_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Resolve navigation candidates (``ref`` only) through their validated receipt."""
    ref = hit.get("ref")
    if hit.get("evidence_contract") == "native-search-evidence-v2" or not isinstance(ref, str):
        return offered_hit(hit)
    if not ref.startswith("sref:"):
        return offered_hit(hit)
    try:
        return resolve_scope_by_ref(ref)
    except SearchReferenceError:
        return {}


def _fragment_from_item(item: dict[str, Any], turn: int, doc_id: str) -> FragmentRef | None:
    """从单块结果或分页 item 里抽出一段片段身份。"""
    text = item.get("text")
    if not isinstance(text, str):
        return None
    locator = str(item.get("locator") or "")
    if not locator:
        return None
    fragment = item.get("fragment")
    if isinstance(fragment, dict):
        start = int(fragment.get("start") or 0)
        end = int(fragment.get("end") or start + len(text))
    else:
        start, end = 0, len(text)
    whole = item.get("text_chars")
    chars = int(whole) if isinstance(whole, int) and whole >= 0 else len(text)
    content_sha = str(item.get("text_sha256") or _sha256(text))
    return FragmentRef(
        doc_id=doc_id,
        build_id=str(item.get("build_id") or ""),
        locator=locator,
        kind=str(item.get("kind") or ""),
        start=start,
        end=end,
        chars=chars,
        content_sha256=content_sha,
        fragment_sha256=_sha256(text),
        turn=turn,
    )


# ── 账本 ─────────────────────────────────────────────────────────────────


@dataclass
class ConsumptionLedger:
    """一次 run 的消费账本：四集合 + 两类完整性之一（范围完整性）。

    ``delivered`` 在**最终消息组装边界**核验（:meth:`finalize`），且只按
    「更强状态胜出」合并：某一路径看不到不代表没送达。
    """

    task_id: str = ""
    role_id: str = ""
    pipeline_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    offered: list[dict[str, Any]] = field(default_factory=list)
    document_identities: list[dict[str, Any]] = field(default_factory=list)
    requested: list[dict[str, Any]] = field(default_factory=list)
    fetched: list[FragmentRef] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Historical originals are usable evidence, not a new request to publish a report.
    replayed_only: bool = False

    #: identity -> 交付状态（delivered／truncated／unknown），跨路径取强。
    delivered: dict[tuple[str, str, int, int], str] = field(default_factory=dict)
    #: 第 0 步审计：每次 fetch 的「返回／送达侧」记录，按 ``tool_call_id`` 与
    #: :attr:`requested` 关联。``delivery_state`` 由 :meth:`finalize` 在真实消息
    #: 边界按四条判据（配对／未被预算替换／快照可恢复／区间与引用完整）推进：
    #: ``unconfirmed`` → ``delivered``／``truncated``／``unknown``／
    #: ``blocked_by_budget``／``snapshot_unrecoverable``；工具自身失败直接记
    #: ``failed``。不进入模型消息；只回答「这次调用实际投递了什么」，与
    #: :attr:`delivered` 的逐片段状态互为补充（前者按调用、后者按片段）。
    responses: list[dict[str, Any]] = field(default_factory=list)
    #: 最近一次在真实消息边界完成送达核验的 turn（-1 = 尚未核验过）。
    #: 环内提交清单的工具用它区分「已核验未送达」与「新取片段待边界核验」。
    last_finalized_turn: int = -1
    #: tool_call_id -> ``cmeta`` 收据句柄。投影隐藏的完整结果由这些收据按调用
    #: 关联，账本落盘时一并保存，便于回放与审计；不进入模型消息。
    metadata_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: native1 检索块 → document1 权威单元原文区间的后台映射表（落盘形态）。
    #: 只接受检索后端 ``native_slices`` 的权威坐标，绝不按 chunk 序号／名称推断；
    #: 缺表时 :meth:`range_completeness` 如实留空，不把检索范围冒充已取回。
    native_mappings: list[dict[str, Any]] = field(default_factory=list)
    #: identity -> 片段 JSON 转义文本（仅内存，用于最终消息核验；不落盘）。
    _fragment_text: dict[tuple[str, str, int, int], str] = field(
        default_factory=dict,
        repr=False,
    )
    _offered_scopes: set[str] = field(default_factory=set, repr=False)
    #: fetched means retrieved raw evidence, not necessarily a corpus_fetch call.
    _fragment_origins: dict[tuple[str, str, int, int], set[str]] = field(
        default_factory=dict, repr=False
    )
    semantic: SemanticConsumption = field(default_factory=SemanticConsumption)

    def has_activity(self) -> bool:
        """Whether this ledger contains a corpus attempt or observation."""
        return bool(
            self.offered
            or self.document_identities
            or self.requested
            or self.fetched
            or self.semantic.calls
            or self.semantic.receipts
        )

    # ── 采集：offered ──────────────────────────────────────────────────
    def _record_document_identity(self, source: dict[str, Any], *, origin: str = "fetch") -> None:
        identity = {key: source[key] for key in
                    ("filename", "document_title", "published", "publication_date_basis")
                    if isinstance(source.get(key), str) and source[key]}
        if not identity or not source.get("doc_id"):
            return
        build_id = source.get("build_id") or str(source["doc_id"]).removeprefix("cv2:")
        record = next((r for r in self.document_identities if
                       r["doc_id"] == source["doc_id"] and r["build_id"] == build_id), None)
        if record is None:
            record = {"doc_id": source["doc_id"], "build_id": build_id, "identity": {},
                      "field_sources": {}, "conflicts": {}}
            self.document_identities.append(record)
        for key, value in identity.items():
            sources = record.setdefault("field_sources", {}).setdefault(key, [])
            observed = {"tool": origin, "value": value}
            if observed not in sources:
                sources.append(observed)
            if key == "publication_date_basis" and value == "unknown":
                continue
            current = record["identity"].get(key)
            if current and current != value:
                record.setdefault("conflicts", {})[key] = list(dict.fromkeys([current, value]))
                record["identity"].pop(key)
            elif key not in record.setdefault("conflicts", {}):
                record["identity"][key] = value

    def record_search(self, result_text: str, *, turn: int = 0) -> None:
        payload = _loads(result_text)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return
        for hit in payload.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            identity = {key: hit[key] for key in
                        ("filename", "document_title", "published", "publication_date_basis")
                        if hit.get(key)}
            if hit.get("published_basis"):
                identity["publication_date_basis"] = hit["published_basis"]
            # Repeated searches can expose new passages within the same scope.
            for item in search_evidence_items(hit):
                self._add_fragment(item, hit["doc_id"], turn, origin=TOOL_SEARCH)
            hit = _offered_hit(hit)
            self._record_document_identity({**hit, **identity}, origin="search")
            mappings = []
            for member in hit.get("context_native_slices") or []:
                mapping = coverage.build_native_mapping(
                    locator=str(member.get("locator") or ""), doc_id=str(hit.get("doc_id") or ""),
                    build_id=str(hit.get("build_id") or ""), rows=member.get("native_slices") or (),
                )
                if mapping is not None:
                    mappings.append(mapping)
            self.record_native_mappings(mappings)
            locators = [str(x) for x in (hit.get("context_locators") or [])]
            if not locators:
                continue
            scope_id = str(hit.get("scope_id") or "")
            key = scope_id or f"{hit.get('doc_id')}|{len(locators)}"
            if key in self._offered_scopes:
                continue
            self._offered_scopes.add(key)
            self.offered.append(
                {
                    "scope_id": scope_id or None,
                    "doc_id": str(hit.get("doc_id") or ""),
                    "build_id": str(hit.get("build_id") or ""),
                    "locators": locators,
                    "total_chunks": int(hit.get("total_chunks") or len(locators)),
                    "by_kind": dict(hit.get("by_kind") or {}),
                    "turn": turn,
                }
            )

    # ── 采集：requested ────────────────────────────────────────────────
    def record_fetch_call(
        self,
        args: Any,
        *,
        turn: int = 0,
        tool_call_id: str = "",
        agent: str = "",
        ordinal: int = 0,
    ) -> None:
        """记录一次 fetch 请求的**请求侧**事实。

        这里只写「请求了什么、目标解析成什么」，不写成功与否；返回侧在
        :meth:`record_fetch_result` 落 :attr:`responses`，两者由 ``tool_call_id`` 关联。

        分类顺序曾把 ``scope == "document"`` 放在 ``ref`` 之前，于是
        ``ref + scope=document``（读整篇的常见写法）被归成 document，ref 永远不会解析，
        请求因此失去文档归属——2026-11-12 的长任务里 17 条请求的 ``doc_id`` 全为空。
        现在 ref 先解析，mode 只描述读取形态。
        """
        if not isinstance(args, dict):
            return
        raw_ref = args.get("ref") if isinstance(args.get("ref"), str) else ""
        raw_cursor = args.get("cursor") if isinstance(args.get("cursor"), str) else ""
        if raw_ref:
            mode = "reference"
            locators = []
        elif args.get("scope") == "document":
            mode = "document"
            locators = []
        elif "locators" in args and isinstance(args.get("locators"), list):
            mode = "batch"
            locators = [str(x) for x in args["locators"]]
        elif args.get("cursor") is not None:
            mode = "cursor"
            locators = []
        else:
            mode = "single"
            locators = [str(args.get("locator") or "")] if args.get("locator") else []

        doc_id = str(args.get("doc_id") or "")
        resolution = "ok" if doc_id else "unresolved"
        resolution_error = ""
        if not doc_id and raw_ref:
            try:
                doc_id = str(resolve_scope_by_ref(raw_ref)["doc_id"])
                resolution = "ok"
            except (SearchReferenceError, KeyError, TypeError) as exc:
                resolution, resolution_error = "unresolved_ref", type(exc).__name__

        # 续读只带 cursor 时，文档身份只能从游标本身解出；解码失败是审计事实，
        # 不是异常——记下原因，绝不让记录动作影响主流程。
        cursor_from: dict[str, int] | None = None
        cursor_type = ""
        if raw_cursor:
            try:
                from plugins.corpus.cursor import decode_cursor

                decoded = decode_cursor(raw_cursor)
                cursor_type = str(decoded.get("type") or "")
                if isinstance(decoded.get("mi"), int) or isinstance(decoded.get("off"), int):
                    cursor_from = {
                        "unit_index": int(decoded.get("mi") or 0),
                        "offset": int(decoded.get("off") or 0),
                    }
                if not doc_id and decoded.get("doc_id"):
                    doc_id = str(decoded["doc_id"])
                    resolution = "ok"
            except Exception as exc:  # CursorError 及其它解码失败
                resolution, resolution_error = "invalid_cursor", type(exc).__name__

        # Failed aliases remain recorded as attempts; they grant no evidence.
        with suppress(SearchReferenceError):
            locators = [canonical_locator(doc_id, loc) for loc in locators]
        self.requested.append(
            {
                "doc_id": doc_id,
                "mode": mode,
                "locators": locators,
                "count": len(locators),
                "view": str(args.get("view") or "full"),
                # 请求预算（未必等于生效预算：全文路径会被策略上限再钳一次）。
                "max_chars": args.get("max_chars"),
                "turn": turn,
                # 原因：工具契约不含「为什么请求」字段，这里如实留空而非编造。
                "reason": "",
                # ── 第 0 步补齐：调用身份与目标解析 ──
                "tool_call_id": str(tool_call_id),
                "agent": str(agent),
                "ordinal": int(ordinal),
                "scope": str(args.get("scope") or ""),
                "ref": raw_ref,
                "cursor_digest": _short_digest(raw_cursor) if raw_cursor else "",
                "cursor_type": cursor_type,
                "cursor_from": cursor_from,
                "unit_range": args.get("unit_range"),
                "resolution": resolution,
                "resolution_error": resolution_error,
                # 请求侧也留关联位：两条请求回执形状一致，合并到哪一条可复核。
                "dedup_of": "",
            }
        )

    # ── 采集：fetched ──────────────────────────────────────────────────
    def record_fetch_result(
        self,
        result_text: str,
        *,
        is_error: bool = False,
        turn: int = 0,
        tool_call_id: str = "",
        internal_chars: int | None = None,
        exposed_chars: int | None = None,
        dedup_of: str = "",
    ) -> None:
        """记录一次 fetch 的**返回侧**事实，并落一条 :attr:`responses`。

        ``internal_chars`` 是后台完整结果的大小（可由调用方从快照物化），
        ``exposed_chars`` 是模型实际看到的字符数；两者都缺省时退化为本条
        ``result_text`` 的长度，绝不会编造一个"更小"的可见值。
        """
        payload = projection.try_materialize(TOOL_FETCH, result_text, tool_call_id=tool_call_id)
        if internal_chars is None:
            internal_chars = len(json.dumps(payload, ensure_ascii=False)) if payload else len(result_text)
        if not isinstance(payload, dict):
            if is_error:
                self._record_error(result_text[:200], turn)
            self._record_response(
                tool_call_id=tool_call_id,
                turn=turn,
                payload={},
                state="failed",
                error=result_text[:200],
                internal_chars=internal_chars,
                exposed_chars=exposed_chars,
                dedup_of=dedup_of,
            )
            return
        if payload.get("ok") is not True:
            self._record_error(str(payload.get("error") or result_text[:200]), turn)
            failure_state = "failed"
            if payload.get("code") == "budget_exceeded":
                failure_state = BLOCKED_BY_BUDGET
            elif payload.get("code") == "metadata_unavailable":
                failure_state = SNAPSHOT_UNRECOVERABLE
            self._record_response(
                tool_call_id=tool_call_id,
                turn=turn,
                payload=payload,
                state=failure_state,
                error=str(payload.get("error") or ""),
                internal_chars=internal_chars,
                exposed_chars=exposed_chars,
                dedup_of=dedup_of,
            )
            return
        doc_id = str(payload.get("doc_id") or "")
        self._record_document_identity(payload)
        refs: list[FragmentRef] = []
        items = payload.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    if payload.get("scope") == "document" and item.get("text") == "":
                        # Empty source units count toward traversal, not quote evidence.
                        continue
                    if payload.get("scope") == "document":
                        item = {"build_id": payload.get("build_id"), **item}
                    ref = self._add_fragment(item, doc_id, turn)
                    if ref is not None:
                        refs.append(ref)
            for err in payload.get("item_errors") or []:
                if isinstance(err, dict):
                    self.errors.append(
                        {
                            "locator": str(err.get("locator") or ""),
                            "code": str(err.get("code") or ""),
                            "error": str(err.get("error") or ""),
                            "turn": turn,
                        }
                    )
            # 未解决成员：显式跳过记录（仍使原范围不完整）。
            for locator in payload.get("unresolved") or []:
                self.skipped.append(
                    {
                        "locator": str(locator),
                        "reason": "unresolved",
                        "turn": turn,
                    }
                )
        else:
            # 单块结果。
            ref = self._add_fragment(payload, doc_id, turn)
            if ref is not None:
                refs.append(ref)
        self._record_response(
            tool_call_id=tool_call_id,
            turn=turn,
            payload=payload,
            state="unconfirmed",
            error="",
            internal_chars=internal_chars,
            exposed_chars=exposed_chars,
            dedup_of=dedup_of,
            doc_id=doc_id,
            refs=refs,
            item_errors=len(payload.get("item_errors") or []),
            unresolved=len(payload.get("unresolved") or []),
        )

    def _record_response(
        self,
        *,
        tool_call_id: str,
        turn: int,
        payload: dict[str, Any],
        state: str,
        error: str,
        internal_chars: int | None,
        exposed_chars: int | None,
        dedup_of: str,
        doc_id: str = "",
        refs: list[FragmentRef] | None = None,
        item_errors: int = 0,
        unresolved: int = 0,
    ) -> None:
        """落一条返回侧记录；``delivery_state`` 初值即"尚未在消息边界核验"。"""
        visible = exposed_chars if isinstance(exposed_chars, int) else None
        self.responses.append(
            {
                "tool_call_id": str(tool_call_id),
                "turn": turn,
                "doc_id": str(doc_id or payload.get("doc_id") or ""),
                "build_id": str(payload.get("build_id") or ""),
                "scope": str(payload.get("scope") or ""),
                "page_id": str(payload.get("page_id") or ""),
                # v1 信封没有该字段；缺省即 v1，绝不默认成新策略。
                "pagination_policy_version": int(payload.get("pagination_policy_version") or 1),
                "effective_max_chars": payload.get("max_chars"),
                "content_scope": payload.get("content_scope"),
                "source_extraction_completeness": "unknown",
                "ranges": [
                    {
                        "locator": ref.locator,
                        "start": ref.start,
                        "end": ref.end,
                        "chars": ref.chars,
                    }
                    for ref in (refs or [])
                ],
                "item_errors": item_errors,
                "unresolved": unresolved,
                "internal_chars": internal_chars,
                "visible_chars": visible,
                "dedup_of": str(dedup_of),
                "delivery_state": state,
                "error": error,
            }
        )

    def record_dedup_response(
        self,
        *,
        tool_call_id: str,
        turn: int = 0,
        dedup_of: str = "",
        visible_chars: int = 0,
        doc_id: str = "",
    ) -> None:
        """落一条同轮去重的**关联回执**：请求记 2、执行记 1、送达只记首份。

        不解析正文、不登记片段、不写 ``ranges`` —— 这条回执本身不是新证据，
        区间并集只认首份，重复请求因此不会把覆盖分子算两遍。

        没有 ``dedup_of`` 时绝不记 ``dedup_ref``：找不到可核对的首条 id，就
        无法在 :meth:`finalize` 验证「首份确实送达」这一省略第二份的前置条件。
        """
        call_id = str(tool_call_id)
        target = str(dedup_of)
        if call_id:
            for row in self.requested:
                if str(row.get("tool_call_id") or "") == call_id:
                    row["dedup_of"] = target
                    break
        self._record_response(
            tool_call_id=call_id,
            turn=turn,
            payload={},
            state=DEDUP_REF if target else UNKNOWN,
            error="" if target else "dedup_target_unidentified",
            internal_chars=None,
            exposed_chars=visible_chars,
            dedup_of=target,
            doc_id=doc_id,
        )

    def record_skip(self, locator: str, *, reason: str, turn: int = 0) -> None:
        self.skipped.append({"locator": str(locator), "reason": reason, "turn": turn})

    def _add_fragment(
        self, item: dict[str, Any], doc_id: str, turn: int, *, origin: str = TOOL_FETCH
    ) -> FragmentRef | None:
        """登记一个片段；重复片段（同文档+同 locator+同字符区间）返回已有引用。

        按 ``unit_id`` 去重会误删续页正文——长单元跨页时同一 unit 会以不同
        ``fragment.start/end`` 到达，因此身份必须含字符区间。
        """
        ref = _fragment_from_item(item, turn, doc_id)
        if ref is None:
            return None
        self._fragment_origins.setdefault(ref.identity, set()).add(origin)
        for existing in self.fetched:
            if existing.identity == ref.identity:
                return existing
        self.fetched.append(ref)
        self._fragment_text[ref.identity] = str(item.get("text"))
        self.delivered.setdefault(ref.identity, UNKNOWN)
        return ref

    def _record_error(self, message: str, turn: int) -> None:
        self.errors.append({"locator": "", "code": "", "error": message, "turn": turn})

    # ── delivered：真实消息边界核验 ────────────────────────────────────
    def finalize(self, messages: list[Message] | None) -> None:
        """在消息里核验每个 fetched 片段是否**仍完整存在**。

        search 原文必须在合法 tool JSON 中同时保留句柄、范围和原文摘要；单独出现
        同文、模型总结或损坏 JSON 均不计送达。纯 fetch 历史路径仍用 JSON 转义文本
        核验。核验不了的片段保持 ``unknown``，合并只取更强状态。

        已判定 ``delivered`` 的片段直接跳过（状态只会更强，重复扫描是纯浪费）；
        这让观察者可以**每个 turn 边界增量调用**（评审 C3：环内校验依赖及时更新
        的送达快照，而不是退出时补账）。
        """
        blob = _messages_blob(messages)
        if not blob:
            return
        source_refs = _delivered_corpus_refs(messages)
        tracked = {
            (row["doc_id"], rng["locator"], rng["start"], rng["end"])
            for row in self.responses if row.get("tool_call_id")
            for rng in row.get("ranges") or []
        }
        for ref in self.fetched:
            if self.delivered.get(ref.identity) == DELIVERED:
                continue
            text = self._fragment_text.get(ref.identity)
            if text is None:
                continue
            if TOOL_SEARCH in self._fragment_origins.get(ref.identity, ()):
                # Text alone is insufficient: dropped hits may share identical text
                # with retained hits. Bind delivery to the complete wire identity.
                status = DELIVERED if _search_signature(ref) in source_refs else UNKNOWN
            else:
                if ref.identity in tracked:
                    continue  # Only the paired final message may qualify a current fetch.
                status = _delivery_status(text, blob)
            current = self.delivered.get(ref.identity, UNKNOWN)
            if delivery_rank(status) > delivery_rank(current):
                self.delivered[ref.identity] = status
        self._finalize_responses(messages)
        self._finalize_dedup_refs()

    def _finalize_responses(self, messages: list[Message] | None) -> None:
        """把每次调用的 ``unconfirmed`` 推进到逐调用的送达状态。

        四条判据缺一不可（这是同轮同参去重"只有第一份确实保留才能省略第二份"
        的前置条件）：

        1. **配对**：按 ``tool_call_id`` 在运行时消息（已经过投影与预算处理）里
           找到对应 tool 消息；找不到就保持 ``unconfirmed``，绝不推断送达；
        2. **未被替换**：可见消息不是预算错误／不可用视图，也没有被字符硬切；
        3. **快照可恢复**：由 ``projection.try_materialize`` 恢复完整内部结果；
           legacy 完整信封由该函数自证返回，导航视图必须拿回 cmeta 收据；
        4. **区间与引用完整**：恢复出的结果里，本次响应的每个区间都能找到
           同 locator + 同码点区间 + 同原文，且非空文本都带 ``evidence_ref``。

        全中 → ``delivered``；部分区间 → ``truncated``；一条都没有 → ``unknown``。
        LLM 是否成功返回、是否"理解了正文"都不参与判定。
        """
        bodies: dict[str, str] = {}
        for message in messages or []:
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                bodies[call_id] = text_of(message.get("content"))
        if not bodies:
            return
        for row in self.responses:
            call_id = str(row.get("tool_call_id") or "")
            body = bodies.get(call_id)
            if body is not None:
                row["visible_chars"] = len(body)
            if row.get("delivery_state") != "unconfirmed":
                continue
            if body is None:  # 判据 1：没有对应消息，不宣称送达
                row["error"] = "pairing_mismatch"
                continue
            row["error"] = ""
            reason = _visible_block_reason(body)
            if reason:
                row["delivery_state"] = BLOCKED_BY_BUDGET
                row["error"] = reason
                continue
            full = _recover_snapshot(body, call_id)
            if full is None:
                row["delivery_state"] = SNAPSHOT_UNRECOVERABLE
                row["error"] = "metadata_snapshot_unavailable_or_invalid"
                continue
            matched, total, issue = _recovered_ranges(full, row, self._fragment_text)
            if issue:
                row["delivery_state"] = TRUNCATED
                row["error"] = issue
            elif matched == total and (total or full.get("exhausted")):
                row["delivery_state"] = DELIVERED
                for rng in row.get("ranges") or []:
                    self.delivered[(row["doc_id"], rng["locator"], rng["start"], rng["end"])] = DELIVERED
            elif matched:
                row["delivery_state"] = TRUNCATED
            else:
                row["delivery_state"] = UNKNOWN

    def _finalize_dedup_refs(self) -> None:
        """关联回执只有在其指向的首份**确实送达**时才成立。

        首份被预算替换、快照不可恢复、区间缺失或没有配对时，省略第二份的
        前提就不存在。这里不改首份状态，只把关联回执降级为
        ``dedup_target_not_delivered``：审计上明确「这条请求仍需重新发起」。
        """
        by_id = {str(row.get("tool_call_id") or ""): row for row in self.responses}
        for row in self.responses:
            if row.get("delivery_state") != DEDUP_REF:
                continue
            target = by_id.get(str(row.get("dedup_of") or ""))
            if target is None:
                row["delivery_state"] = DEDUP_TARGET_NOT_DELIVERED
                row["error"] = "dedup_target_missing"
            elif target.get("delivery_state") != DELIVERED:
                row["delivery_state"] = DEDUP_TARGET_NOT_DELIVERED
                row["error"] = f"dedup_target_{target.get('delivery_state')}"

    def dedup_accounting(self) -> dict[str, int]:
        """可复算的「请求 N／执行 M／唯一送达 K」账目。

        ``executions`` 只数没有 ``dedup_of`` 的响应（真实执行过的调用）；
        ``unique_deliveries`` 只数 ``delivered`` 的响应，关联回执不计入；
        覆盖区间并集另由 :meth:`coverage_deliveries` 按片段身份去重。
        """
        return {
            "requests": len(self.requested),
            "executions": sum(1 for row in self.responses if not row.get("dedup_of")),
            "unique_deliveries": sum(
                1 for row in self.responses if row.get("delivery_state") == DELIVERED
            ),
            "dedup_refs": sum(1 for row in self.responses if row.get("dedup_of")),
            "unresolved_dedup_refs": sum(
                1 for row in self.responses
                if row.get("delivery_state") == DEDUP_TARGET_NOT_DELIVERED
            ),
        }

    def delivered_status(self, identity: tuple[str, str, int, int]) -> str:
        return self.delivered.get(identity, UNKNOWN)

    def coverage_deliveries(self) -> list[Any]:
        """覆盖映射的输入：按**片段**取已确认送达的区间。

        只取 :attr:`delivered` 里 ``delivered`` 状态的身份，跨轮／跨 agent 的重复
        片段在这里天然只出现一次；区间并集由 ``coverage.delivered_union`` 再做一次
        （长单元跨页分片会首尾相接，必须合并，不能按 unit_id 去重）。
        同轮同参去重的关联回执不登记任何片段，因此重复请求不会把同一区间
        在分子里算两遍。
        """
        from plugins.corpus.coverage import Delivery

        return [
            Delivery(doc_id=doc, locator=locator, start=start, end=end)
            for (doc, locator, start, end), status in self.delivered.items()
            if status == DELIVERED
        ]

    def coverage_map(
        self, units: list[Any], *, doc_id: str = "", page_count: int = 0
    ) -> dict[str, Any]:
        """按目标文档版本的原始区间出覆盖报告；``units`` 为 ``UnitRange`` 列表。"""
        from plugins.corpus.coverage import coverage_report

        resolved = (
            doc_id
            or next(
                (str(row.get("doc_id") or "") for row in self.responses if row.get("doc_id")),
                "",
            )
            or next((identity[0] for identity in self.delivered), "")
        )
        return coverage_report(
            doc_id=resolved,
            units=units,
            deliveries=self.coverage_deliveries(),
            page_count=page_count,
        )

    # ── 区间覆盖（评审 C1：出现 ≠ 完整）────────────────────────────────
    def _intervals_for(
        self,
        locator: str,
        *,
        delivered_only: bool = False,
    ) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for ref in self.fetched:
            if ref.locator != locator:
                continue
            if delivered_only and self.delivered_status(ref.identity) != DELIVERED:
                continue
            out.append((ref.start, ref.end))
        return out

    def _locator_chars(self, locator: str) -> int:
        for ref in self.fetched:
            if ref.locator == locator and ref.chars > 0:
                return ref.chars
        return 0

    # ── 后台映射表 ─────────────────────────────────────────────────────
    def record_native_mappings(self, mappings: list[Any]) -> None:
        """合并 ``native1 → document1`` 后台映射；同 locator 切片取并集。

        只接受 :func:`coverage.mappings_from_fetch` 从权威 ``native_slices``
        校验过的条目；落盘形态稳定排序，便于离线回放复算。
        """
        existing = coverage.mappings_from_dict(self.native_mappings)
        merged = coverage.merge_native_mappings([*existing, *mappings])
        self.native_mappings = [row.to_dict() for row in merged]

    # ── 范围完整性 ─────────────────────────────────────────────────────
    def range_completeness(self) -> list[dict[str, Any]]:
        """按 offered scope 汇总：必需片段是否**全部**取回／送达（范围完整性）。

        评审 C1：locator 出现 ≠ 范围完整。非 ``native1`` 成员按片段 ``[start, end)``
        区间并集对比整块长度（``chars``）判定；``native1`` 成员在后台映射表可用时，
        按其绑定的权威单元原文区间与 ``document1`` 送达区间折算——两套 locator
        不强行归一，缺表则维持原语义并显式列入 ``unmapped``。
        """
        from plugins.corpus.preparation.document_read import unit_locator

        mappings = coverage.mappings_from_dict(self.native_mappings)
        table: dict[str, Any] = {}

        def native_covered(loc: str, *, delivered_only: bool) -> bool | None:
            """``None`` = 没有后台映射，调用方维持原 locator 直查语义。"""
            slices = table.get(loc)
            if not slices:
                return None
            for item in slices:
                intervals = self._intervals_for(
                    unit_locator(item.unit_id), delivered_only=delivered_only
                )
                clipped = coverage.merge_intervals(
                    (max(item.start, a), min(item.end, b))
                    for a, b in intervals
                    if a < item.end and item.start < b
                )
                if sum(b - a for a, b in clipped) < item.end - item.start:
                    return False
            return True

        out: list[dict[str, Any]] = []
        for scope in self.offered:
            table = coverage.native_unit_intervals([
                m for m in mappings if m.doc_id == scope.get("doc_id")
            ])
            locators = list(scope.get("locators") or [])
            missing: list[str] = []
            undelivered: list[str] = []
            unmapped: list[str] = []
            for loc in locators:
                native = loc.startswith(coverage.NATIVE_PREFIX)
                mapped = native_covered(loc, delivered_only=False) if native else None
                if mapped is None:
                    chars = self._locator_chars(loc)
                    fetched_ok = _covers_whole(self._intervals_for(loc), chars)
                    delivered_ok = _covers_whole(
                        self._intervals_for(loc, delivered_only=True), chars
                    )
                    if native:
                        unmapped.append(loc)
                else:
                    # A direct native read may already cover the complete block;
                    # mapping is an additional way to prove coverage, not a replacement.
                    chars = self._locator_chars(loc)
                    fetched_ok = mapped or _covers_whole(self._intervals_for(loc), chars)
                    delivered_ok = bool(native_covered(loc, delivered_only=True)) or _covers_whole(
                        self._intervals_for(loc, delivered_only=True), chars
                    )
                if not fetched_ok:
                    missing.append(loc)
                if not delivered_ok:
                    undelivered.append(loc)
            skipped = [
                str(item.get("locator"))
                for item in self.skipped
                if str(item.get("locator")) in set(locators)
            ]
            out.append(
                {
                    "scope_id": scope.get("scope_id"),
                    "doc_id": scope.get("doc_id"),
                    "total": len(locators),
                    "fetched": len(locators) - len(missing),
                    "delivered": len(locators) - len(undelivered),
                    "missing": missing,
                    "undelivered": undelivered,
                    "unmapped": unmapped,
                    "skipped": skipped,
                    # 有未取全、未送达或跳过 ⇒ 范围不完整。
                    "complete": not missing and not undelivered and not skipped,
                }
            )
        return out

    def all_offered_fetched(self) -> bool | None:
        """历史指标 ``all_returned_context_fetched``：提供范围是否全部取回。

        无 offered（未走 corpus_search）时为 ``None``——没提供范围就无所谓完整性，
        不冒充通过。它**不是** delivered 指标，也不是全部结论的通过条件。
        """
        if not self.offered:
            return None
        return all(
            row["fetched"] == row["total"] and row["total"] > 0 for row in self.range_completeness()
        )

    # ── 序列化 ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "task_id": self.task_id,
            "role_id": self.role_id,
            "pipeline_id": self.pipeline_id,
            "created_at": self.created_at,
            "last_finalized_turn": self.last_finalized_turn,
            "offered": self.offered,
            "document_identities": self.document_identities,
            "requested": self.requested,
            "responses": self.responses,
            "dedup_accounting": self.dedup_accounting(),
            "semantic": self.semantic.to_dict(),
            "fetched": [
                {
                    **ref.to_dict(),
                    "retrieved_via": sorted(self._fragment_origins.get(ref.identity, ())),
                }
                for ref in self.fetched
            ],
            "delivered": [
                {
                    "doc_id": ref.doc_id,
                    "locator": ref.locator,
                    "start": ref.start,
                    "end": ref.end,
                    "status": self.delivered_status(ref.identity),
                }
                for ref in self.fetched
            ],
            "errors": self.errors,
            "skipped": self.skipped,
            "notes": self.notes,
            "metadata_snapshots": self.metadata_snapshots,
            "native_mappings": self.native_mappings,
            "range_completeness": self.range_completeness(),
            "all_offered_fetched": self.all_offered_fetched(),
        }


def _search_signature(ref: FragmentRef) -> tuple[Any, ...]:
    return (*ref.identity, ref.build_id, ref.chars, ref.content_sha256, ref.fragment_sha256)


def _delivered_corpus_refs(messages: list[Message] | None) -> set[tuple[Any, ...]]:
    """Recognize intact search/fetch evidence in final tool messages, never summaries.

    The hidden metadata is read from the receipt-backed complete result, but a
    fragment only counts as delivered when its verbatim text is *still present*
    in the visible message. A saved snapshot therefore never promotes an
    item that the budget fitter dropped to delivered.
    """
    refs: set[tuple[Any, ...]] = set()
    for message in messages or []:
        name = message.get("name")
        if message.get("role") != "tool" or name not in (None, TOOL_SEARCH, TOOL_FETCH):
            continue
        visible_text = text_of(message.get("content"))
        visible_payload = _loads(visible_text)
        if not isinstance(visible_payload, dict) or visible_payload.get("ok") is not True:
            continue
        tool_name = (
            name
            if isinstance(name, str)
            else (TOOL_SEARCH if "hits" in visible_payload else TOOL_FETCH)
        )
        payload = projection.try_materialize(
            tool_name,
            visible_text,
            tool_call_id=str(message.get("tool_call_id") or ""),
        )
        if payload is None:
            # A projected message with an unresolvable receipt must not have its
            # hidden wire fields reconstructed from the visible view. Text-based
            # delivery verification (the message blob) still applies below.
            continue

        def add(item: dict[str, Any], doc_id: str, *, blob: str = visible_text) -> None:
            text = item.get("text")
            if not isinstance(text, str) or _delivery_status(text, blob) != DELIVERED:
                return
            ref = _fragment_from_item(item, 0, doc_id)
            if ref is not None:
                refs.add(_search_signature(ref))

        hits = payload.get("hits")
        if not isinstance(hits, list):
            # A later fetch can deliver the same interval that search offered.
            if tool_name != TOOL_SEARCH and isinstance(payload.get("doc_id"), str):
                items = payload.get("items", [payload])
                for item in items if isinstance(items, list) else []:
                    if isinstance(item, dict):
                        add(item, payload["doc_id"])
            continue
        if tool_name == TOOL_FETCH:
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            doc_id = hit.get("doc_id")
            if not isinstance(doc_id, str):
                continue
            for item in search_evidence_items(hit):
                add(item, doc_id)
    return refs


def _loads(text: Any) -> Any:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _messages_blob(messages: list[Message] | None) -> str:
    if not messages:
        return ""
    parts: list[str] = []
    for message in messages:
        try:
            parts.append(text_of(message.get("content")))
        except Exception:
            continue
    return "\n".join(parts)


def _delivery_status(text: str, blob: str) -> str:
    """片段是否完整出现在最终消息里：完整=delivered、半截=truncated、看不到=unknown。"""
    if not text:
        return UNKNOWN
    if not blob:
        return UNKNOWN
    escaped = _escaped(text)
    if escaped and escaped in blob:
        return DELIVERED
    if len(escaped) > TRUNCATED_MIN_PREFIX:
        head = escaped[:TRUNCATED_MIN_PREFIX]
        if head and head in blob:
            return TRUNCATED
    return UNKNOWN


def _visible_block_reason(body: str) -> str:
    """判据 2/3：可见消息是否被预算处理替换成错误、不可用视图或残缺内容。

    只拦"正文/契约被替换"的情形；去掉诊断元数据（``diagnostics_elided``／
    ``view_fallback``／``*_count``）不算截断正文，交给判据 4 校验区间即可。
    """
    try:
        visible = json.loads(body)
    except (TypeError, ValueError):
        return "malformed_message_json"
    if not isinstance(visible, dict):
        return "malformed_message_json"
    tool = visible.get("tool")
    if tool and tool != TOOL_FETCH:
        return "tool_call_mismatch"
    if visible.get("ok") is False or visible.get("error") or visible.get("code"):
        return "budget_or_error_replacement"
    if visible.get("protocol") == projection.UNAVAILABLE_VERSION:
        return "metadata_unavailable_view"
    if visible.get("cursor_omitted"):
        return "continuation_contract_omitted"
    if visible.get("text_chars") and "text" not in visible and "items" not in visible:
        return "body_removed_by_budget"
    return ""


def _recover_snapshot(body: str, tool_call_id: str) -> dict[str, Any] | None:
    """判据 4：恢复完整内部结果；恢复不了就是不可恢复，不拿可见摘要顶替。"""
    with suppress(Exception):
        return projection.try_materialize(TOOL_FETCH, body, tool_call_id=tool_call_id)
    return None


def _recovered_ranges(
    full: dict[str, Any],
    row: dict[str, Any],
    fragment_text: dict[tuple[str, str, int, int], str],
) -> tuple[int, int, str]:
    """判据 4：恢复结果里逐区间核对原文与引用，返回 (命中, 总数, 阻断原因)。"""
    if full.get("doc_id") != row.get("doc_id"):
        return 0, 0, "response_document_mismatch"
    items = full.get("items")
    if not isinstance(items, list):
        items = [full] if full.get("text") is not None else []
    by_key: dict[tuple[str, int, int], str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        fragment = item.get("fragment") or {}
        key = (
            str(item.get("locator") or ""),
            int(fragment.get("start", 0)),
            int(fragment.get("end", len(text))),
        )
        if text and not item.get("evidence_ref"):
            return 0, 0, "recovered_reference_missing"
        by_key[key] = text
    ranges = [rng for rng in row.get("ranges") or [] if isinstance(rng, dict)]
    doc_id = str(row.get("doc_id") or "")
    matched = 0
    for rng in ranges:
        key = (
            str(rng.get("locator") or ""),
            int(rng.get("start") or 0),
            int(rng.get("end") or 0),
        )
        text = by_key.get(key)
        if text is None:
            continue
        expected = fragment_text.get((doc_id, *key))
        if expected is not None and text != expected:
            continue
        matched += 1
    return matched, len(ranges), ""


def fetch_delivery_complete(raw: str, visible: str) -> bool:
    """Tool-owned validation before a duplicate may point at the first final message."""
    if _visible_block_reason(visible):
        return False
    full = projection.try_materialize(TOOL_FETCH, visible)
    expected = projection.try_materialize(TOOL_FETCH, raw)
    if full is None or expected is None:
        return False
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(json.dumps(expected, ensure_ascii=False), tool_call_id="check")
    if not ledger.responses or ledger.responses[0]["delivery_state"] != "unconfirmed":
        return False
    matched, total, issue = _recovered_ranges(full, ledger.responses[0], ledger._fragment_text)
    return not issue and matched == total and bool(total or expected.get("exhausted"))


# ── run 级共享账本 ───────────────────────────────────────────────────────


def run_ledger_key() -> str:
    """当前 run 的账本键：优先 ``APODEX_RUN_DIR``，否则进程内单例。"""
    return os.environ.get(_RUN_DIR_ENV, "").strip() or "__process__"


def get_run_ledger(
    key: str | None = None,
    *,
    task_id: str = "",
    role_id: str = "",
    pipeline_id: str = "",
) -> ConsumptionLedger:
    """取（或建）同一 run 共享的账本；子代理与主循环追加同一份。"""
    resolved = key or run_ledger_key()
    ledger = _LEDGERS.get(resolved)
    if ledger is None:
        ledger = ConsumptionLedger(
            task_id=task_id,
            role_id=role_id,
            pipeline_id=pipeline_id,
        )
        _LEDGERS[resolved] = ledger
    else:
        # 首个写入者之外的调用补齐缺失身份（不覆盖已有值）。
        ledger.task_id = ledger.task_id or task_id
        ledger.role_id = ledger.role_id or role_id
        ledger.pipeline_id = ledger.pipeline_id or pipeline_id
    return ledger


def reset_run_ledgers() -> None:
    """测试用：清空进程内共享账本。"""
    _LEDGERS.clear()


# ── 落盘（独立 JSON 工件）────────────────────────────────────────────────


def resolve_artifact_dir() -> Path | None:
    """run artifacts 目录：``<APODEX_RUN_DIR>/corpus``；无 run 目录则不落盘。"""
    run_dir = os.environ.get(_RUN_DIR_ENV, "").strip()
    if not run_dir:
        return None
    return Path(run_dir) / _ARTIFACT_SUBDIR


def _write_json(directory: Path | None, filename: str, payload: dict[str, Any]) -> Path | None:
    if directory is None:
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / filename
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target
    except OSError as exc:
        logger.warning("corpus ledger: 写 %s 失败：%s", filename, exc)
        return None


def write_ledger(
    ledger: ConsumptionLedger,
    *,
    directory: Path | None = None,
) -> Path | None:
    return _write_json(directory or resolve_artifact_dir(), LEDGER_FILENAME, ledger.to_dict())


def load_manifest(*, directory: Path | None = None) -> dict[str, Any] | None:
    """读取旧版单文件清单；缺文件返回 ``None``。新契约请用 :func:`load_manifest_files`。"""
    folder = directory or resolve_artifact_dir()
    if folder is None:
        return None
    target = folder / MANIFEST_FILENAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _manifest_sort_key(path: Path) -> tuple[int, str]:
    """子清单排序键：按 ``manifest-NNN`` 的**数值**序号，缺序号退回文件名。

    数值排序而非字典序，才能保证「后者取代前者」（:func:`_merge_manifests` 用文件
    顺序确定同拥有者的最新提交）在序号过千（``manifest-1000``）时仍然成立。
    """
    stem = path.stem.removeprefix("manifest-")
    if stem.isdigit():
        return (int(stem), path.name)
    return (1 << 30, path.name)


def load_manifest_files(
    directory: Path | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    """按修订契约读取全部候选清单（评审 C4），按提交序号升序。

    ``manifests/*.json`` 为主（各代理／各次提交独立落盘，互不覆盖）；仅当该目录
    为空时才回读旧版单文件 ``manifest.json``（兼容历史运行，不与新契约双算）。
    """
    folder = directory or resolve_artifact_dir()
    if folder is None:
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    sub = folder / MANIFESTS_SUBDIR
    if sub.is_dir():
        for path in sorted(sub.glob("*.json"), key=_manifest_sort_key):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("corpus ledger: 清单 %s 不可解析，已跳过", path)
                continue
            if isinstance(payload, dict):
                out.append((path, payload))
    if out:
        return out
    legacy = folder / MANIFEST_FILENAME
    if legacy.is_file():
        try:
            payload = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(payload, dict):
            out.append((legacy, payload))
    return out


def write_manifest_file(
    payload: dict[str, Any],
    *,
    directory: Path | None = None,
    owner: str = "",
) -> Path | None:
    """把一份候选清单落盘为独立子清单文件（``manifests/manifest-NNN.json``）。

    文件名按现有序号递增，**绝不覆盖**既有清单；没有 run 目录时不落盘（返回
    ``None``），调用方仍可做环内回验。写失败同样返回 ``None`` 并记日志。

    ``owner`` 非空时写入 ``owner_role``（已有值不覆盖）：它是**聚合键**——跨拥有
    者并集、同拥有者取最新（见 :func:`_merge_manifests`）。因此同一代理的多次提交
    会取代自己先前的候选（「重新提交完整清单」），而不同代理／子代理之间仍互补。
    """
    folder = directory or resolve_artifact_dir()
    if folder is None:
        return None
    document = dict(payload)
    if owner and not document.get("owner_role"):
        document["owner_role"] = owner
    try:
        sub = folder / MANIFESTS_SUBDIR
        sub.mkdir(parents=True, exist_ok=True)
        index = 0
        for path in sub.glob("manifest-*.json"):
            stem = path.stem.removeprefix("manifest-")
            if stem.isdigit():
                index = max(index, int(stem) + 1)
        target = sub / f"manifest-{index:03d}.json"
        target.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target
    except OSError as exc:
        logger.warning("corpus ledger: 写子清单失败：%s", exc)
        return None


def _manifest_owner(path: Path, payload: dict[str, Any]) -> str:
    """候选清单的拥有者：显式 ``owner_role`` 优先，否则退回文件名。

    ``owner_role`` 由提交方（``corpus_submit_manifest``）按当前代理实例写入，是
    「同拥有者取代」的聚合键。退回文件名只用于兼容历史／手工产物——它会让每次
    提交各成一个拥有者、退化为「全量并集」（旧行为），不再具备取代语义。
    """
    return str(payload.get("owner_role") or path.stem or "manifest")


def _merge_manifests(
    manifests: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    """把多份候选清单汇成一份待验证清单：**跨拥有者并集、同拥有者取最新**。

    多拥有者（多代理／多子代理）时结论 id 加拥有者前缀防撞并互相补充；同一拥有者
    的多次提交是「重新提交完整清单」，按提交序号**后者取代前者**——否则环内已修正
    的结论会被它自己的旧候选拖回 ``partial``（校验语义缺陷 F2）。
    """
    latest: dict[str, tuple[Path, dict[str, Any]]] = {}
    order: list[str] = []
    for path, payload in manifests:
        owner = _manifest_owner(path, payload)
        if owner not in latest:
            order.append(owner)
        latest[owner] = (path, payload)  # 载入序即提交序 → 后者取代前者
    multi = len(order) > 1
    conclusions: list[Any] = []
    for owner in order:
        payload = latest[owner][1]
        rows = payload.get("conclusions")
        if not isinstance(rows, list):
            conclusions.append(
                {
                    "invalid_manifest": True,
                    "owner": owner,
                    "reason": "清单缺 conclusions 数组",
                }
            )
            continue
        for row in rows:
            if isinstance(row, dict):
                row = dict(row)
                row.pop("report_binding", None)
                if "report_binding" in payload:
                    row["report_binding"] = payload["report_binding"]
            if multi and isinstance(row, dict):
                row = {**row, "id": f"{owner}/{row.get('id') or ''}"}
            conclusions.append(row)
    first = manifests[0][1]
    return {
        "schema_version": first.get("schema_version"),
        "conclusions": conclusions,
    }


def write_verification(
    payload: dict[str, Any],
    *,
    directory: Path | None = None,
) -> Path | None:
    return _write_json(
        directory or resolve_artifact_dir(),
        VERIFICATION_FILENAME,
        payload,
    )


def verify_and_record(
    ledger: ConsumptionLedger,
    *,
    manifest: dict[str, Any] | None = None,
    directory: Path | None = None,
    resolver: SourceResolver | None = None,
    final_text: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验清单并落盘验证工件；缺清单则记录 draft。

    - ``final_text`` 提供时做**报告绑定**校验（``report_quote`` 锚点必须出现在
      最终文本中；评审 C4）；
    - ``extra`` 合并进落盘工件（如边界动作、发布状态），schema 纯增量；
    - 基础设施异常映射为 ``verification_error``，与确定性缺口/缺清单分开
      （评审 C7）——校验失败绝不被描述成校验通过。
    """
    folder = directory or resolve_artifact_dir()
    try:
        manifests = (
            [(Path("<memory>"), manifest)] if manifest is not None else load_manifest_files(folder)
        )
        if not manifests and not ledger.has_activity():
            verification = {
                "schema_version": VERIFICATION_SCHEMA_VERSION,
                "status": "not_applicable",
                "reason": "本轮无语料检索或引用，语料证据清单校验不适用",
                "conclusions": [],
            }
        elif not manifests:
            verification = {
                "schema_version": VERIFICATION_SCHEMA_VERSION,
                "status": PUBLISH_DRAFT,
                "reason": "缺少结论证据清单：产物只能作为草稿，不得标记为已通过证据完整性校验",
                "conclusions": [],
            }
        else:
            selected = manifests
            if final_text is not None:
                finals = [item for item in manifests if item[1].get("report_target") == "final_answer"]
                if finals:
                    # Research drafts remain auditable, but their old anchors are
                    # not the final answer. File deliverables retain independent bindings.
                    latest = {_manifest_owner(path, payload): (path, payload)
                              for path, payload in manifests}
                    selected = [item for item in latest.values() if
                                (item[1].get("report_binding") or {}).get("path")]
                    selected.append(finals[-1])
            merged = _merge_manifests(selected)
            verification = verify_manifest(
                merged,
                ledger,
                resolver=resolver,
                final_text=final_text,
            )
            verification["manifest_files"] = [str(path) for path, _ in manifests]
            verification["checked_manifest_files"] = [str(path) for path, _ in selected]
    except Exception as exc:
        logger.warning("corpus ledger: 清单校验基础设施故障：%s", exc)
        verification = {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "status": PUBLISH_VERIFICATION_ERROR,
            "reason": f"校验基础设施异常：{type(exc).__name__}: {exc}",
            "conclusions": [],
        }
    if final_text is not None:
        verification["report_sha256"] = _sha256(final_text)
        verification["report_chars"] = len(final_text)
    if extra:
        verification.update(extra)
    path = write_verification(verification, directory=folder)
    verification["artifact_path"] = str(path) if path is not None else None
    return verification


# ── 结论证据清单校验 ─────────────────────────────────────────────────────

#: ``(doc_id, locator) -> 权威原文``；返回 ``None`` 表示该来源无法解析。
SourceResolver = Callable[[str, str], "str | None"]


def _default_resolver(doc_id: str, locator: str) -> str | None:
    """权威原文解析：确定性拒绝（句柄不存在／旧句柄）返回 ``None``，
    基础设施异常**向上抛**（由 ``_verify_conclusion`` 分类为 ``verification_error``，
    评审 C7——吞掉异常会把故障误判成证据缺口）。"""
    from plugins.corpus.service import get_service

    return get_service().fetch_verbatim(doc_id, locator).text


_INFRA_ERROR_MARKERS = (
    "timeout",
    "connection",
    "unavailable",
    "unreachable",
    "operational",
    "storeerror",
    "refused",
    "reset",
)


def _is_infra_error(exc: Exception) -> bool:
    """区分基础设施故障与确定性拒绝（评审 C7）。"""
    if isinstance(exc, ConnectionError | TimeoutError | OSError):
        return True
    name = type(exc).__name__.lower()
    if any(marker in name for marker in _INFRA_ERROR_MARKERS):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _INFRA_ERROR_MARKERS)


def _evidence_delivery(
    ledger: ConsumptionLedger,
    doc_id: str,
    locator: str,
    quote_start: int,
    quote_end: int,
) -> str:
    """引文区间 ``[quote_start, quote_end)`` 是否被**已送达**片段覆盖。

    评审 C1：只看「该 locator 有片段送达」不够——只读首段时，未送达区间里的
    引文不能因服务端全文可查而放行。返回 ``delivered``（区间被已送达片段并集
    覆盖）／``partial``（有已送达片段但未覆盖引文区间）／``unknown``（无可判定
    的已送达片段）。
    """
    refs = [ref for ref in ledger.fetched if ref.doc_id == doc_id and ref.locator == locator]
    if not refs:
        return UNKNOWN
    delivered_intervals = [
        (ref.start, ref.end) for ref in refs if ledger.delivered_status(ref.identity) == DELIVERED
    ]
    if not delivered_intervals:
        return UNKNOWN
    if _covers_interval(delivered_intervals, quote_start, quote_end):
        return DELIVERED
    return "partial"


def verify_manifest(
    manifest: dict[str, Any],
    ledger: ConsumptionLedger,
    *,
    resolver: SourceResolver | None = None,
    final_text: str | None = None,
    pending_aware: bool = False,
) -> dict[str, Any]:
    """由账本与权威原文**重算**每条结论的状态；不接受模型自报通过。

    每条结论的 ``status``：

    - ``unsupported``：证据缺失或无效（评审 C2：非对象条目一律拒绝，不静默跳过）、
      quote 无法溯源（编造）或来源无法解析；
    - ``partial``：quote 可溯源，但引文区间未被完整送达（评审 C1：按区间覆盖判，
      不是「locator 出现过」）、声明的必要依赖未被覆盖，或报告锚点缺失／不匹配
      （评审 C4，仅在提供 ``final_text`` 时检查）；
    - ``supported``：quote 逐字可溯源、引文区间完整送达、声明依赖全覆盖。

    ``pending_aware=True`` 供**环内提交**使用：尚未经过消息边界核验的新取片段
    记 ``pending`` 而不是 ``unknown``（评审 C3），问题消息区分「待核验」与
    「确认未送达」。发布边界汇总时保持默认严格模式。

    任一结论出现 ``verification_error``（校验基础设施故障）时，整体状态为
    ``verification_error``——校验不可信时不得给出任何「已校验」结论（评审 C7）。
    """
    resolve = resolver or _default_resolver
    conclusions_out: list[dict[str, Any]] = []
    for index, conclusion in enumerate(manifest.get("conclusions") or []):
        if not isinstance(conclusion, dict):
            # 评审 C2：非法结论条目不再静默跳过——跳过会让「空有效清单」伪装通过。
            conclusions_out.append(
                {
                    "id": f"C{index + 1}",
                    "status": UNSUPPORTED,
                    "evidence_count": 0,
                    "covered_purposes": [],
                    "missing_dependencies": [],
                    "delivery": [],
                    "problems": [
                        {
                            "code": "invalid_conclusion",
                            "message": f"conclusions[{index}] 不是 JSON 对象，已拒绝",
                        }
                    ],
                    "model_claimed_complete": None,
                }
            )
            continue
        binding = conclusion.get("report_binding", manifest.get("report_binding"))
        report_text = final_text
        binding_problems: list[dict[str, str]] = []
        if binding is not None:
            from plugins.corpus.report_binding import bound_report

            if isinstance(binding, dict) and binding.get("kind") == "inline":
                submitted = binding.get("text")
                if (not isinstance(submitted, str) or not submitted.strip()
                        or _sha256(submitted) != binding.get("sha256")
                        or final_text is None or submitted not in final_text):
                    binding_problems = [{"code": "report_changed_or_unavailable",
                                         "message": "最终正文已变化，须重新绑定本次交付清单"}]
            else:
                report_text, binding_problems = bound_report(binding)
        row = _verify_conclusion(
            conclusion,
            index,
            ledger,
            resolve,
            report_text,
            pending_aware=pending_aware,
        )
        if binding is not None:
            row["report_binding"] = binding
        if binding_problems:
            row["problems"].extend(binding_problems)
            if row["status"] == SUPPORTED:
                row["status"] = PARTIAL
        conclusions_out.append(row)
    counts = {SUPPORTED: 0, PARTIAL: 0, UNSUPPORTED: 0}
    for row in conclusions_out:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    verification_errors = sum(
        1
        for row in conclusions_out
        if any(p.get("code") == "verification_error" for p in row.get("problems") or [])
    )
    if not conclusions_out:
        status = PUBLISH_DRAFT
    elif verification_errors:
        status = PUBLISH_VERIFICATION_ERROR
    elif counts[UNSUPPORTED] and counts[UNSUPPORTED] == len(conclusions_out):
        status = PUBLISH_UNSUPPORTED
    elif counts[PARTIAL] or counts[UNSUPPORTED]:
        status = PUBLISH_PARTIAL
    else:
        status = PUBLISH_VERIFIED
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": status,
        "counts": counts,
        "verification_errors": verification_errors,
        "range_completeness": ledger.range_completeness(),
        "all_offered_fetched": ledger.all_offered_fetched(),
        "conclusions": conclusions_out,
    }


#: 未获支持即整体不可信的确定性缺口（评审 C2：无效条目属于此类，不静默）。
_UNSUPPORTED_CODES = {
    "no_evidence",
    "invalid_evidence",
    "invalid_conclusion",
    "incomplete_evidence",
    "source_unresolvable",
    "quote_not_found",
}


def _verify_conclusion(
    conclusion: dict[str, Any],
    index: int,
    ledger: ConsumptionLedger,
    resolve: SourceResolver,
    final_text: str | None = None,
    *,
    pending_aware: bool = False,
) -> dict[str, Any]:
    if "document_identity" in conclusion:
        from plugins.corpus.final_delivery import verify_identity_conclusion

        return verify_identity_conclusion(conclusion, ledger, final_text)
    cid = str(conclusion.get("id") or f"C{index + 1}")
    evidence = conclusion.get("evidence")
    problems: list[dict[str, str]] = []
    covered_purposes: set[str] = set()
    deliveries: list[str] = []
    semantic_out: list[dict[str, Any]] = []
    matched_evidence: list[dict[str, Any]] = []

    # 评审 C4：报告绑定——结论必须能在最终报告中定位；清单与报告脱节即降级。
    report_quote = str(conclusion.get("report_quote") or "").strip()
    if final_text is not None:
        if not report_quote:
            problems.append(
                {
                    "code": "not_in_report",
                    "message": "清单未提供报告定位锚点 report_quote，无法确认该结论位于最终报告",
                }
            )
        elif report_quote not in final_text:
            problems.append(
                {
                    "code": "not_in_report",
                    "message": "report_quote 未出现在最终报告中（清单相对报告已过期）",
                }
            )

    semantic_refs = conclusion.get("semantic_references")
    if semantic_refs is not None:
        if not isinstance(semantic_refs, list) or not semantic_refs:
            problems.append(
                {"code": "invalid_evidence", "message": "semantic_references 必须为非空数组"}
            )
        else:
            for raw in semantic_refs:
                try:
                    ref = ReportSemanticReference.model_validate(raw)
                except ValueError as exc:
                    problems.append({"code": "invalid_evidence", "message": str(exc)})
                    continue
                if ref.report_quote != report_quote:
                    problems.append(
                        {"code": "not_in_report", "message": "语义引用与结论 report_quote 不一致"}
                    )
                checked, issues = verify_reference(
                    ref,
                    ledger.semantic,
                    final_text=final_text,
                    pending_aware=pending_aware,
                )
                semantic_out.append(checked.model_dump(mode="json"))
                problems.extend(issues)
                deliveries.append(checked.delivery_status)
                if checked.verification_status == "verified":
                    covered_purposes.update(
                        d.kind
                        for d in checked.dependency_assertions
                        if d.status == "present" and checked.purpose in d.required_for
                    )

    if (not isinstance(evidence, list) or not evidence) and semantic_refs is None:
        problems.append({"code": "no_evidence", "message": "结论未附任何证据"})
    if evidence is not None and not isinstance(evidence, list):
        problems.append({"code": "invalid_evidence", "message": "evidence 必须为数组"})
    if isinstance(evidence, list):
        for ev_index, item in enumerate(evidence):
            label = f"evidence[{ev_index}]"
            if not isinstance(item, dict):
                # 评审 C2：非法证据条目一律拒绝并登记，绝不静默跳过——
                # 跳过会让「零有效证据」伪装成 supported。
                problems.append(
                    {
                        "code": "invalid_evidence",
                        "message": f"{label} 不是 JSON 对象，已拒绝",
                    }
                )
                continue
            doc_id = str(item.get("doc_id") or "").strip()
            locator = str(item.get("locator") or "").strip()
            pinned_range = "source_start" in item or "source_end" in item
            quote = str(item.get("quote") or "")
            if not pinned_range:
                quote = quote.strip()
            purpose = str(item.get("purpose") or "").strip()
            if purpose:
                covered_purposes.add(purpose)
            if not doc_id or not locator or not quote:
                problems.append(
                    {
                        "code": "incomplete_evidence",
                        "message": f"{label} 缺少 doc_id／locator／quote，溯源链断开",
                    }
                )
                continue
            try:
                locator = canonical_locator(doc_id, locator)
                source_text = resolve(doc_id, locator)
            except Exception as exc:
                # 评审 C7：基础设施故障与确定性缺口分开——
                # 故障记 verification_error，整体校验状态降为不可信。
                code = "verification_error" if _is_infra_error(exc) else "source_unresolvable"
                problems.append(
                    {
                        "code": code,
                        "message": (
                            f"{label} 的 {doc_id}|{locator} 解析权威原文时失败"
                            f"（{type(exc).__name__}：{exc}）"
                        ),
                    }
                )
                continue
            if source_text is None:
                problems.append(
                    {
                        "code": "source_unresolvable",
                        "message": f"{label} 的 {doc_id}|{locator} 无法解析到原文",
                    }
                )
                continue
            matches = list(find_quote_matches(source_text, quote))
            if pinned_range:
                start, end = item.get("source_start"), item.get("source_end")
                # Receipt-derived coordinates select this exact occurrence, not
                # another identical quote in a delivered part of the same block.
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= len(source_text)
                    or source_text[start:end] != quote
                ):
                    matches = []
                else:
                    matches = [m for m in matches if m.start == start and m.end == end]
            if not matches:
                problems.append(
                    {
                        "code": "quote_not_found",
                        "message": f"{label} 的 quote 未在原文中逐字出现：{quote[:60]!r}",
                    }
                )
                continue
            # A search excerpt may expose a later occurrence of the same quote.
            # The first textual match alone must not hide a delivered interval.
            check_delivery = evidence_delivery_for_submit if pending_aware else _evidence_delivery
            delivery = UNKNOWN
            ranks = {UNKNOWN: 0, "partial": 1, "pending": 2, DELIVERED: 3}
            chosen = matches[0]
            for match in matches:
                candidate = check_delivery(ledger, doc_id, locator, match.start, match.end)
                if ranks.get(candidate, 0) > ranks.get(delivery, 0):
                    delivery = candidate
                    chosen = match
                if delivery == DELIVERED:
                    break
            matched_evidence.append(
                {
                    "doc_id": doc_id,
                    "locator": locator,
                    "start": chosen.start,
                    "end": chosen.end,
                    "quote": chosen.text,
                    "match_kind": chosen.kind,
                    "delivery": delivery,
                }
            )
            if pending_aware and delivery == "pending":
                problems.append(
                    {
                        "code": "pending_delivery",
                        "message": (
                            f"{label} 的片段已取回但尚未经过下一轮消息边界核验；"
                            "请下一轮重新提交完整清单确认"
                        ),
                    }
                )
                continue
            deliveries.append(delivery)
            if delivery != DELIVERED:
                problems.append(
                    {
                        "code": "not_delivered",
                        "message": (
                            f"{label} 的引文区间未被已送达片段完整覆盖"
                            f"（{delivery}）；评审 C1：只读首段不等于整块送达"
                        ),
                    }
                )

    required = [str(dep) for dep in (conclusion.get("required_dependencies") or [])]
    missing_deps = [dep for dep in required if dep not in covered_purposes]
    if missing_deps:
        problems.append(
            {
                "code": "missing_dependencies",
                "message": "声明的必要依赖未被任何证据用途覆盖：" + "、".join(missing_deps),
            }
        )

    if any(p["code"] in _UNSUPPORTED_CODES for p in problems):
        status = UNSUPPORTED
    elif problems:
        status = PARTIAL
    else:
        status = SUPPORTED
    return {
        "id": cid,
        "text_location": str(conclusion.get("text_location") or ""),
        "report_quote": report_quote,
        "status": status,
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "covered_purposes": sorted(covered_purposes),
        "missing_dependencies": missing_deps,
        "delivery": sorted(set(deliveries)),
        "semantic_references": semantic_out,
        "matched_evidence": matched_evidence,
        "problems": problems,
        # 明确忽略模型自报：字段仅记录，不参与判定。
        "model_claimed_complete": conclusion.get("complete"),
    }


# ── 发布边界（评审 C5/C6）────────────────────────────────────────────────
#: 阻断开关：``A4_ENFORCE`` ∈ {1,true,yes,on}（大小写不敏感）时在发布边界
#: 执行确定性降级；**默认关闭**（评审 §7：默认启用暂缓，先小规模观测对照）。
_ENFORCE_ENV = "A4_ENFORCE"


def enforcement_enabled() -> bool:
    raw = os.environ.get(_ENFORCE_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _limitation_block(verification: dict[str, Any]) -> str:
    """确定性降级块（评审 C6）：列出每条未支持结论及其**可定位锚点**与问题码。

    只追加不删改——这是较弱的「草稿保留」产品目标：读者仍能看到原结论，但每条
    未支持结论都带着锚点与问题码被显式标注，明细落盘可复算。完全的「修正／删除
    无支持结论」需要在环内由清单反馈驱动修正后重新提交（工具契约），或未来引入
    确定性的文本手术。
    """
    status = verification.get("status")
    if status == PUBLISH_DRAFT:
        return (
            "---\n\n"
            "> **证据完整性校验（A4）**：缺少结论证据清单（manifest），本报告只能"
            "按未校验草稿对待，不得引用为已通过证据完整性校验；"
            "明细见 corpus/manifest_verification.json。"
        )
    if status == PUBLISH_VERIFICATION_ERROR:
        return (
            "---\n\n"
            "> **证据完整性校验（A4）**：校验基础设施故障，结论证据状态**无法可靠"
            "判定**，本报告按未校验草稿对待；明细见 corpus/manifest_verification.json。"
        )
    lines: list[str] = []
    for row in verification.get("conclusions") or []:
        if not isinstance(row, dict) or row.get("status") == SUPPORTED:
            continue
        codes = sorted(
            {str(p.get("code") or "") for p in row.get("problems") or [] if isinstance(p, dict)}
        )
        anchor = str(row.get("report_quote") or row.get("text_location") or "").strip()
        where = f"「{anchor[:40]}…」附近" if anchor else "位置未提供"
        lines.append(
            f"> - {row.get('id')}（{where}）：{'、'.join(codes) or '未获完整支持'}",
        )
    head = f"> **证据完整性校验（A4）**：本报告未完全通过结论证据校验（状态：{status}）。"
    tail = "> 明细见 corpus/manifest_verification.json。"
    if lines:
        return "\n".join(
            [
                "---",
                "",
                head,
                "> 以下结论存在证据支持、送达或报告对应问题，具体原因如下：",
                *lines,
                tail,
            ]
        )
    return "\n".join(["---", "", head, "> 部分结论未获完整证据支持。", tail])


def publish_boundary(
    ledger: ConsumptionLedger,
    *,
    final_text: str,
    answer_status: str,
    directory: Path | None = None,
    resolver: SourceResolver | None = None,
    announce_status: bool = False,
) -> dict[str, Any]:
    """所有最终发布路径共用的 A4 边界（评审 C5）。

    返回 ``{"boundary_action", "publish_status", "final_text", "answer_status",
    "verification"}``：

    - ``skip``：本 run 无 corpus 活动（非语料任务）——原样放行，不写工件；
    - ``publish``：校验通过——原样放行（工件已落盘）；
    - ``observe``：默认模式（``A4_ENFORCE`` 未开）或基础设施故障 fail-open——
      记录状态与工件，不改变发布内容；**观测与放行不等于校验通过**；
    - ``downgrade``：enforce 开启且未通过——按评审 C6 追加确定性限定块
      （逐条锚定），``answer_status`` 由 ``complete`` 降为 ``partial``
      （已是 ``not_found``／``best_effort`` 的保持原值，不往弱处反向升级）。
    """
    outcome: dict[str, Any] = {
        "boundary_action": "observe",
        "publish_status": "",
        "final_text": final_text,
        "answer_status": answer_status,
        "verification": None,
    }
    try:
        if ledger.replayed_only:
            outcome["boundary_action"] = "skip"
            return outcome
        if not ledger.has_activity():
            outcome["boundary_action"] = "skip"
            outcome["publish_status"] = "not_applicable"
            return outcome
        verification = verify_and_record(
            ledger,
            directory=directory,
            resolver=resolver,
            final_text=final_text,
            extra={"boundary_answer_status": answer_status},
        )
        outcome["verification"] = verification
        outcome["publish_status"] = verification.get("status") or ""
        rows = verification.get("conclusions") or []
        identity_only = outcome["publish_status"] == PUBLISH_VERIFIED and bool(rows) and all(
            row.get("verification_kind") == "document_identity" for row in rows
        )
        if announce_status and not identity_only:
            passed = outcome["publish_status"] == PUBLISH_VERIFIED
            status_text = "已通过" if passed else "未全部通过，以本次最终核验为准"
            counts = verification.get("counts") or {}
            supported = counts.get("supported", 0)
            total = sum(counts.values())
            notice = (
                f"最终证据核验：{status_text}（{supported}/{total} 条清单结论）。"
                "仅核验清单所绑定的内容，不代表全文事实已独立核实。"
            )
            report_codes = {"not_in_report", "report_changed_or_unavailable"}
            rows = verification.get("conclusions") or []
            report_failures = sum(
                any(p.get("code") in report_codes for p in row.get("problems", [])) for row in rows
            )
            if report_failures:
                evidence_supported = sum(
                    bool(row.get("evidence_count") or row.get("semantic_references"))
                    and not any(p.get("code") not in report_codes for p in row.get("problems", []))
                    for row in rows
                )
                notice = (
                    f"最终证据核验：未全部通过。原文证据及送达核验 {evidence_supported}/{total}；"
                    f"报告引用对应核验 {total - report_failures}/{total}。"
                    "部分引用未对应最终报告，或绑定文件已变化/不可读；交付未完成核验。"
                    "报告对应失败不等于原文证据全部错误。"
                )
            outcome["final_text"] = f"{final_text.rstrip()}\n\n> {notice}"
            if not passed and answer_status == "complete":
                outcome["answer_status"] = "partial"
        if outcome["publish_status"] == PUBLISH_VERIFIED:
            outcome["boundary_action"] = "publish"
            return outcome
        if not enforcement_enabled():
            return outcome
        outcome["final_text"] += f"\n\n{_limitation_block(verification)}"
        if outcome["answer_status"] == "complete":
            outcome["answer_status"] = "partial"
        outcome["boundary_action"] = "downgrade"
        return outcome
    except Exception as exc:
        logger.warning("corpus ledger: 发布边界执行失败（fail-open）：%s", exc)
        outcome["boundary_action"] = "observe"
        return outcome


def evidence_delivery_for_submit(
    ledger: ConsumptionLedger,
    doc_id: str,
    locator: str,
    quote_start: int,
    quote_end: int,
) -> str:
    """环内提交清单用的送达判定：在 :func:`_evidence_delivery` 基础上区分
    「已核验未送达」与「新取片段待边界核验」（评审 C3）。

    返回 ``delivered``／``partial``／``truncated``／``pending``／``not_delivered``：
    新取片段（取回 turn 晚于最近一次消息边界核验）标 ``pending``——它将在本轮
    结束的消息边界被核验，下一轮重新提交即可确认，不诱发无效补取。
    """
    refs = [ref for ref in ledger.fetched if ref.doc_id == doc_id and ref.locator == locator]
    if not refs:
        return UNKNOWN
    status = _evidence_delivery(ledger, doc_id, locator, quote_start, quote_end)
    if status != UNKNOWN:
        return status
    if any(ref.turn > ledger.last_finalized_turn for ref in refs):
        return "pending"
    return "not_delivered"


# ── 观察者（观测模式，绝不阻断）────────────────────────────────────────────


class ConsumptionLedgerObserver(BaseObserver):
    """采集 offered／requested／fetched，并在 loop 结束核验 delivered、落盘。

    挂到 stateful_react 主循环与 agent_team 子代理／主循环的观察者列表即可。
    所有钩子都 best-effort：任何异常都被 loop 的观察者隔离机制吞掉，不影响运行。
    """

    def __init__(
        self,
        *,
        task_id: str = "",
        role_id: str = "",
        pipeline_id: str = "",
        ledger: ConsumptionLedger | None = None,
    ) -> None:
        self._task_id = task_id
        self._role_id = role_id
        self._pipeline_id = pipeline_id
        self._ledger = ledger
        # 本 loop 已扫描过的消息数（增量送达核验；评审 C3）。
        self._scanned_messages = 0
        # (agent, turn) -> 该轮第几次 fetch 调用。同轮同参去重要靠它区分先后，
        # 不能只看 turn（同一轮可并发多个 fetch）。
        self._ordinals: dict[tuple[str, int], int] = {}

    def _next_ordinal(self, turn: int) -> int:
        key = (self._role_id, turn)
        ordinal = self._ordinals.get(key, 0) + 1
        self._ordinals[key] = ordinal
        return ordinal

    def _get_ledger(self) -> ConsumptionLedger:
        if self._ledger is None:
            self._ledger = get_run_ledger(
                task_id=self._task_id,
                role_id=self._role_id,
                pipeline_id=self._pipeline_id,
            )
        return self._ledger

    def _restore_replayed_evidence(self, messages: list) -> None:
        """Recover receipts only from paired tool messages in the validated replay.

        Never hydrate summaries or unpaired user/assistant text. Reuse the ordinary
        parsers and delivery checks; final verification still resolves source text.
        This does not rewrite history or make an archived file visible to the model.
        """
        if getattr(self, "_replay_restored", False):
            return
        self._replay_restored = True
        ledger = self._get_ledger()
        had_activity = bool(ledger.offered or ledger.fetched or ledger.semantic.calls)
        calls: dict[str, tuple[str, dict]] = {}
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    if fn.get("name") not in {TOOL_SEARCH, TOOL_FETCH}:
                        continue
                    args = _loads(fn.get("arguments") or "{}")
                    if isinstance(args, dict) and call.get("id"):
                        calls[call["id"]] = (fn["name"], args)
            elif message.get("role") == "tool":
                prior = calls.pop(str(message.get("tool_call_id") or ""), None)
                content = message.get("content")
                if prior is None or not isinstance(content, str):
                    continue
                name, args = prior
                call_id = str(message.get("tool_call_id") or "")
                complete = projection.try_materialize(name, content, tool_call_id=call_id)
                complete_text = (
                    json.dumps(complete, ensure_ascii=False)
                    if isinstance(complete, dict)
                    else content
                )
                if name == TOOL_SEARCH:
                    ledger.record_search(complete_text, turn=0)
                else:
                    ledger.record_fetch_call(
                        args, turn=0, tool_call_id=call_id, agent=self._role_id
                    )
                    replay_payload = _loads(content)
                    if isinstance(replay_payload, dict) and replay_payload.get("dedup") is True:
                        # 历史里的同轮去重关联回执不是一次失败，更不是新送达的
                        # 正文；重放必须保持 dedup_ref 语义，不能记成 failed。
                        ledger.record_dedup_response(
                            tool_call_id=call_id,
                            turn=0,
                            dedup_of=str(replay_payload.get("dedup_of") or ""),
                            visible_chars=len(content),
                        )
                        continue
                    ledger.record_fetch_result(
                        complete_text,
                        turn=0,
                        tool_call_id=call_id,
                        internal_chars=len(complete_text),
                    )
                    ledger.record_native_mappings(
                        coverage.mappings_from_fetch(_loads(complete_text))
                    )
        ledger.finalize(messages)
        ledger.last_finalized_turn = max(0, ledger.last_finalized_turn)
        if not had_activity:
            ledger.replayed_only = bool(ledger.offered or ledger.fetched)

    async def on_tool_call(
        self,
        ctx: TurnContext,
        tool_call: dict,
    ) -> None:
        try:
            self._restore_replayed_evidence(list(getattr(ctx, "messages", None) or []))
            name = str(tool_call.get("name") or "")
            if name in {TOOL_SEARCH, TOOL_FETCH, SEMANTIC_TOOL, "corpus_submit_manifest"}:
                self._get_ledger().replayed_only = False
            if name not in {TOOL_FETCH, SEMANTIC_TOOL}:
                return
            args = tool_call.get("args")
            if isinstance(args, dict):
                if name == SEMANTIC_TOOL:
                    self._get_ledger().semantic.record_call(
                        args,
                        str(tool_call.get("id") or ""),
                        ctx.turn,
                    )
                else:
                    self._get_ledger().record_fetch_call(
                        args,
                        turn=ctx.turn,
                        tool_call_id=str(tool_call.get("id") or ""),
                        agent=self._role_id,
                        ordinal=self._next_ordinal(ctx.turn),
                    )
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_tool_call: %s", exc)

    async def on_tool_result(
        self,
        ctx: TurnContext,
        result: ToolResult,
    ) -> None:
        try:
            self._restore_replayed_evidence(list(getattr(ctx, "messages", None) or []))
            name = result.name
            if name in {TOOL_SEARCH, TOOL_FETCH, SEMANTIC_TOOL}:
                self._get_ledger().replayed_only = False
            if name == TOOL_SEARCH:
                self._get_ledger().record_search(result.result, turn=ctx.turn)
            elif name == TOOL_FETCH:
                ledger = self._get_ledger()
                if result.execution_status == "dedup_ref":
                    # 合并后的关联回执：只记一条响应侧审计行，绝不解析成正文
                    # 片段，也绝不新增送达。
                    payload = _loads(result.result)
                    ledger.record_dedup_response(
                        tool_call_id=str(result.tool_call_id or ""),
                        turn=ctx.turn,
                        dedup_of=(
                            str(payload.get("dedup_of") or "")
                            if isinstance(payload, dict) else ""
                        ),
                        visible_chars=len(result.result),
                    )
                else:
                    ledger.record_fetch_result(
                        result.result,
                        is_error=result.is_error,
                        turn=ctx.turn,
                        tool_call_id=str(result.tool_call_id or ""),
                    )
                    # 权威后台映射只在工具返回的原始结果里（投影白名单不含
                    # native_slices）；在 notify_tool_result 边界采集，不依赖
                    # 模型最终看到的那份可见视图。
                    payload = projection.try_materialize(TOOL_FETCH, result.result,
                                                         tool_call_id=str(result.tool_call_id or ""))
                    if isinstance(payload, dict):
                        ledger.record_native_mappings(coverage.mappings_from_fetch(payload))
            elif name == SEMANTIC_TOOL:
                self._get_ledger().semantic.record_result(
                    result.args,
                    result.result,
                    result.tool_call_id,
                    ctx.turn,
                )
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_tool_result: %s", exc)

    @staticmethod
    def _sync_snapshots(ledger: ConsumptionLedger, messages: list) -> None:
        """Bind cmeta receipts by tool_call_id and surface unresolved projections."""
        for call_id, ref in projection.call_snapshot_refs().items():
            ledger.metadata_snapshots.setdefault(call_id, {"snapshot_ref": ref})
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            body = text_of(message.get("content"))
            payload = _loads(body)
            if not isinstance(payload, dict) or payload.get("protocol") not in (
                projection.VISIBLE_VERSION,
                projection.NAVIGATION_VERSION,
            ):
                continue
            name = str(message.get("name") or "")
            if not name:
                name = TOOL_SEARCH if "hits" in payload else TOOL_FETCH
            call_id = str(message.get("tool_call_id") or "")
            if projection.try_materialize(name, body, tool_call_id=call_id) is None:
                note = f"corpus_metadata_snapshot_unavailable:{call_id or 'unpaired'}"
                if note not in ledger.notes:
                    ledger.notes.append(note)

    async def on_turn_end(self, ctx: TurnContext) -> None:
        """在每个 turn 结束（下一轮真实模型请求之前）增量核验送达快照。

        评审 C3：环内提交清单需要**及时更新**的 delivered 状态；只在
        ``on_loop_end`` 补账会让新取片段永远 ``unknown``，修正闭环失效。
        只扫本轮新增的消息（``finalize`` 对已 delivered 片段幂等跳过，压缩改写
        历史时按更坏情况整表重扫一次，合并取强不会降级）。
        """
        try:
            self._restore_replayed_evidence(list(getattr(ctx, "messages", None) or []))
            ledger = self._get_ledger()
            messages = list(ctx.messages or [])
            start = self._scanned_messages if self._scanned_messages <= len(messages) else 0
            if len(messages) > start:
                ledger.finalize(messages[start:])
                self._sync_snapshots(ledger, messages[start:])
            self._scanned_messages = len(messages)
            if ctx.turn > ledger.last_finalized_turn:
                ledger.last_finalized_turn = ctx.turn
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_turn_end: %s", exc)

    async def on_loop_end(self, result: AgentLoopResult) -> None:
        try:
            ledger = self._get_ledger()
            ledger.finalize(result.messages)
            self._sync_snapshots(ledger, list(result.messages or []))
            write_ledger(ledger)
            verify_and_record(ledger)
        except Exception as exc:
            logger.warning("ConsumptionLedgerObserver.on_loop_end: %s", exc)


__all__ = [
    "CORPUS_TOOLS",
    "DEDUP_REF",
    "DEDUP_TARGET_NOT_DELIVERED",
    "DELIVERED",
    "DEPENDENCY_PURPOSES",
    "LEDGER_FILENAME",
    "LEDGER_SCHEMA_VERSION",
    "MANIFESTS_SUBDIR",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "PARTIAL",
    "PUBLISH_DRAFT",
    "PUBLISH_PARTIAL",
    "PUBLISH_UNSUPPORTED",
    "PUBLISH_VERIFICATION_ERROR",
    "PUBLISH_VERIFIED",
    "SKIPPED",
    "SUPPORTED",
    "TRUNCATED",
    "UNKNOWN",
    "UNSUPPORTED",
    "VERIFICATION_FILENAME",
    "VERIFICATION_SCHEMA_VERSION",
    "ConsumptionLedger",
    "ConsumptionLedgerObserver",
    "FragmentRef",
    "delivery_rank",
    "enforcement_enabled",
    "evidence_delivery_for_submit",
    "evidence_rank",
    "get_run_ledger",
    "load_manifest",
    "load_manifest_files",
    "publish_boundary",
    "reset_run_ledgers",
    "resolve_artifact_dir",
    "run_ledger_key",
    "verify_and_record",
    "verify_manifest",
    "write_ledger",
    "write_manifest_file",
    "write_verification",
]
