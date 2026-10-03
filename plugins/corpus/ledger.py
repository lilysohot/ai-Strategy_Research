"""A4 消费账本与结论证据校验：offered／requested／fetched／delivered + 两类完整性。

为什么需要这一层：``corpus_search`` 提供了上下文候选、``corpus_fetch`` 返回了原文，
但「检索提供了什么」与「模型最终看到了什么」之间隔着两层截断——工作流后处理
（``ReactToolResultPostProcessor``）与单轮聚合预算（``_overflow``）。全部落在
trajectory 里的全文，并不等于进入了**最终模型请求**。本模块把这条链路的四个
状态分辨清楚：

| 状态 | 来源 | 不能混同为 |
|---|---|---|
| ``offered`` | 检索提供的完整候选范围 | 已被要求读取的范围 |
| ``requested`` | Agent 显式选定并请求的范围 | 已取回 |
| ``fetched`` | 服务成功返回的块／片段 | 已完整送达模型 |
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
    "value", "period", "unit", "header", "footnote", "condition", "negation", "attribution",
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
    return bool(merged) and merged[0][0] == 0 and merged[-1][1] >= chars


def _covers_interval(
    intervals: list[tuple[int, int]], start: int, end: int,
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
    requested: list[dict[str, Any]] = field(default_factory=list)
    fetched: list[FragmentRef] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: identity -> 交付状态（delivered／truncated／unknown），跨路径取强。
    delivered: dict[tuple[str, str, int, int], str] = field(default_factory=dict)
    #: 最近一次在真实消息边界完成送达核验的 turn（-1 = 尚未核验过）。
    #: 环内提交清单的工具用它区分「已核验未送达」与「新取片段待边界核验」。
    last_finalized_turn: int = -1
    #: identity -> 片段 JSON 转义文本（仅内存，用于最终消息核验；不落盘）。
    _fragment_text: dict[tuple[str, str, int, int], str] = field(
        default_factory=dict, repr=False,
    )
    _offered_scopes: set[str] = field(default_factory=set, repr=False)
    semantic: SemanticConsumption = field(default_factory=SemanticConsumption)

    # ── 采集：offered ──────────────────────────────────────────────────
    def record_search(self, result_text: str, *, turn: int = 0) -> None:
        payload = _loads(result_text)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return
        for hit in payload.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            locators = [str(x) for x in (hit.get("context_locators") or [])]
            if not locators:
                continue
            scope_id = str(hit.get("scope_id") or "")
            key = scope_id or f"{hit.get('doc_id')}|{len(locators)}"
            if key in self._offered_scopes:
                continue
            self._offered_scopes.add(key)
            self.offered.append({
                "scope_id": scope_id or None,
                "doc_id": str(hit.get("doc_id") or ""),
                "build_id": str(hit.get("build_id") or ""),
                "locators": locators,
                "total_chunks": int(hit.get("total_chunks") or len(locators)),
                "by_kind": dict(hit.get("by_kind") or {}),
                "turn": turn,
            })

    # ── 采集：requested ────────────────────────────────────────────────
    def record_fetch_call(self, args: Any, *, turn: int = 0) -> None:
        if not isinstance(args, dict):
            return
        if "locators" in args and isinstance(args.get("locators"), list):
            mode = "batch"
            locators = [str(x) for x in args["locators"]]
        elif args.get("cursor") is not None:
            mode = "cursor"
            locators = []
        else:
            mode = "single"
            locators = [str(args.get("locator") or "")] if args.get("locator") else []
        self.requested.append({
            "doc_id": str(args.get("doc_id") or ""),
            "mode": mode,
            "locators": locators,
            "count": len(locators),
            "view": str(args.get("view") or "full"),
            "max_chars": args.get("max_chars"),
            "turn": turn,
            # 原因：工具契约不含「为什么请求」字段，这里如实留空而非编造。
            "reason": "",
        })

    # ── 采集：fetched ──────────────────────────────────────────────────
    def record_fetch_result(
        self, result_text: str, *, is_error: bool = False, turn: int = 0,
    ) -> None:
        payload = _loads(result_text)
        if not isinstance(payload, dict):
            if is_error:
                self._record_error(result_text[:200], turn)
            return
        if payload.get("ok") is not True:
            self._record_error(str(payload.get("error") or result_text[:200]), turn)
            return
        doc_id = str(payload.get("doc_id") or "")
        items = payload.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    self._add_fragment(item, doc_id, turn)
            for err in payload.get("item_errors") or []:
                if isinstance(err, dict):
                    self.errors.append({
                        "locator": str(err.get("locator") or ""),
                        "code": str(err.get("code") or ""),
                        "error": str(err.get("error") or ""),
                        "turn": turn,
                    })
            # 未解决成员：显式跳过记录（仍使原范围不完整）。
            for locator in payload.get("unresolved") or []:
                self.skipped.append({
                    "locator": str(locator),
                    "reason": "unresolved",
                    "turn": turn,
                })
            return
        # 单块结果。
        self._add_fragment(payload, doc_id, turn)

    def record_skip(self, locator: str, *, reason: str, turn: int = 0) -> None:
        self.skipped.append({"locator": str(locator), "reason": reason, "turn": turn})

    def _add_fragment(self, item: dict[str, Any], doc_id: str, turn: int) -> None:
        ref = _fragment_from_item(item, turn, doc_id)
        if ref is None:
            return
        if any(existing.identity == ref.identity for existing in self.fetched):
            return
        self.fetched.append(ref)
        self._fragment_text[ref.identity] = str(item.get("text"))
        self.delivered.setdefault(ref.identity, UNKNOWN)

    def _record_error(self, message: str, turn: int) -> None:
        self.errors.append({"locator": "", "code": "", "error": message, "turn": turn})

    # ── delivered：真实消息边界核验 ────────────────────────────────────
    def finalize(self, messages: list[Message] | None) -> None:
        """在消息里核验每个 fetched 片段是否**仍完整存在**。

        比对用片段文本的 JSON 转义形式（消息正文是 ``json.dumps(..., ensure_ascii=False)``
        的结果），既覆盖未截断的合法 JSON，也覆盖被 head-cap 切坏的 JSON。核验不了
        的片段保持 ``unknown``——不推断为已送达。合并只取更强状态。

        已判定 ``delivered`` 的片段直接跳过（状态只会更强，重复扫描是纯浪费）；
        这让观察者可以**每个 turn 边界增量调用**（评审 C3：环内校验依赖及时更新
        的送达快照，而不是退出时补账）。
        """
        blob = _messages_blob(messages)
        if not blob:
            return
        for ref in self.fetched:
            if self.delivered.get(ref.identity) == DELIVERED:
                continue
            text = self._fragment_text.get(ref.identity)
            if text is None:
                continue
            status = _delivery_status(text, blob)
            current = self.delivered.get(ref.identity, UNKNOWN)
            if delivery_rank(status) > delivery_rank(current):
                self.delivered[ref.identity] = status

    def delivered_status(self, identity: tuple[str, str, int, int]) -> str:
        return self.delivered.get(identity, UNKNOWN)

    # ── 区间覆盖（评审 C1：出现 ≠ 完整）────────────────────────────────
    def _intervals_for(
        self, locator: str, *, delivered_only: bool = False,
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

    # ── 范围完整性 ─────────────────────────────────────────────────────
    def range_completeness(self) -> list[dict[str, Any]]:
        """按 offered scope 汇总：必需片段是否**全部**取回／送达（范围完整性）。

        评审 C1：locator 出现 ≠ 范围完整。按片段 ``[start, end)`` 区间并集对比
        整块长度（``chars``）判定；整块长度未知（``chars==0``）时按不完整处理，
        不冒充通过。
        """
        out: list[dict[str, Any]] = []
        for scope in self.offered:
            locators = list(scope.get("locators") or [])
            missing: list[str] = []
            undelivered: list[str] = []
            for loc in locators:
                chars = self._locator_chars(loc)
                if not _covers_whole(self._intervals_for(loc), chars):
                    missing.append(loc)
                if not _covers_whole(self._intervals_for(loc, delivered_only=True), chars):
                    undelivered.append(loc)
            skipped = [
                str(item.get("locator"))
                for item in self.skipped
                if str(item.get("locator")) in set(locators)
            ]
            out.append({
                "scope_id": scope.get("scope_id"),
                "doc_id": scope.get("doc_id"),
                "total": len(locators),
                "fetched": len(locators) - len(missing),
                "delivered": len(locators) - len(undelivered),
                "missing": missing,
                "undelivered": undelivered,
                "skipped": skipped,
                # 有未取全、未送达或跳过 ⇒ 范围不完整。
                "complete": not missing and not undelivered and not skipped,
            })
        return out

    def all_offered_fetched(self) -> bool | None:
        """历史指标 ``all_returned_context_fetched``：提供范围是否全部取回。

        无 offered（未走 corpus_search）时为 ``None``——没提供范围就无所谓完整性，
        不冒充通过。它**不是** delivered 指标，也不是全部结论的通过条件。
        """
        if not self.offered:
            return None
        return all(row["fetched"] == row["total"] and row["total"] > 0
                   for row in self.range_completeness())

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
            "requested": self.requested,
            "semantic": self.semantic.to_dict(),
            "fetched": [ref.to_dict() for ref in self.fetched],
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
            "range_completeness": self.range_completeness(),
            "all_offered_fetched": self.all_offered_fetched(),
        }


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
            task_id=task_id, role_id=role_id, pipeline_id=pipeline_id,
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
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        return target
    except OSError as exc:
        logger.warning("corpus ledger: 写 %s 失败：%s", filename, exc)
        return None


def write_ledger(
    ledger: ConsumptionLedger, *, directory: Path | None = None,
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
    payload: dict[str, Any], *, directory: Path | None = None, owner: str = "",
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
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8",
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
            conclusions.append({
                "invalid_manifest": True,
                "owner": owner,
                "reason": "清单缺 conclusions 数组",
            })
            continue
        for row in rows:
            if multi and isinstance(row, dict):
                row = {**row, "id": f"{owner}/{row.get('id') or ''}"}
            conclusions.append(row)
    first = manifests[0][1]
    return {
        "schema_version": first.get("schema_version"),
        "conclusions": conclusions,
    }


def write_verification(
    payload: dict[str, Any], *, directory: Path | None = None,
) -> Path | None:
    return _write_json(
        directory or resolve_artifact_dir(), VERIFICATION_FILENAME, payload,
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
            [(Path("<memory>"), manifest)] if manifest is not None
            else load_manifest_files(folder)
        )
        if not manifests:
            verification = {
                "schema_version": VERIFICATION_SCHEMA_VERSION,
                "status": PUBLISH_DRAFT,
                "reason": "缺少结论证据清单：产物只能作为草稿，不得标记为已通过证据完整性校验",
                "conclusions": [],
            }
        else:
            merged = _merge_manifests(manifests)
            verification = verify_manifest(
                merged, ledger, resolver=resolver, final_text=final_text,
            )
            verification["manifest_files"] = [str(path) for path, _ in manifests]
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
    "timeout", "connection", "unavailable", "unreachable", "operational",
    "storeerror", "refused", "reset",
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
    refs = [
        ref for ref in ledger.fetched
        if ref.doc_id == doc_id and ref.locator == locator
    ]
    if not refs:
        return UNKNOWN
    delivered_intervals = [
        (ref.start, ref.end) for ref in refs
        if ledger.delivered_status(ref.identity) == DELIVERED
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
            conclusions_out.append({
                "id": f"C{index + 1}",
                "status": UNSUPPORTED,
                "evidence_count": 0,
                "covered_purposes": [],
                "missing_dependencies": [],
                "delivery": [],
                "problems": [{
                    "code": "invalid_conclusion",
                    "message": f"conclusions[{index}] 不是 JSON 对象，已拒绝",
                }],
                "model_claimed_complete": None,
            })
            continue
        conclusions_out.append(
            _verify_conclusion(
                conclusion, index, ledger, resolve, final_text,
                pending_aware=pending_aware,
            ),
        )
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
    "no_evidence", "invalid_evidence", "invalid_conclusion",
    "incomplete_evidence", "source_unresolvable", "quote_not_found",
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
    cid = str(conclusion.get("id") or f"C{index + 1}")
    evidence = conclusion.get("evidence")
    problems: list[dict[str, str]] = []
    covered_purposes: set[str] = set()
    deliveries: list[str] = []
    semantic_out: list[dict[str, Any]] = []

    # 评审 C4：报告绑定——结论必须能在最终报告中定位；清单与报告脱节即降级。
    report_quote = str(conclusion.get("report_quote") or "").strip()
    if final_text is not None:
        if not report_quote:
            problems.append({
                "code": "not_in_report",
                "message": "清单未提供报告定位锚点 report_quote，无法确认该结论位于最终报告",
            })
        elif report_quote not in final_text:
            problems.append({
                "code": "not_in_report",
                "message": "report_quote 未出现在最终报告中（清单相对报告已过期）",
            })

    semantic_refs = conclusion.get("semantic_references")
    if semantic_refs is not None:
        if not isinstance(semantic_refs, list) or not semantic_refs:
            problems.append({"code": "invalid_evidence", "message": "semantic_references 必须为非空数组"})
        else:
            for raw in semantic_refs:
                try:
                    ref = ReportSemanticReference.model_validate(raw)
                except ValueError as exc:
                    problems.append({"code": "invalid_evidence", "message": str(exc)})
                    continue
                if ref.report_quote != report_quote:
                    problems.append({"code": "not_in_report", "message": "语义引用与结论 report_quote 不一致"})
                checked, issues = verify_reference(
                    ref, ledger.semantic, final_text=final_text, pending_aware=pending_aware,
                )
                semantic_out.append(checked.model_dump(mode="json"))
                problems.extend(issues)
                deliveries.append(checked.delivery_status)
                if checked.verification_status == "verified":
                    covered_purposes.update(
                        d.kind for d in checked.dependency_assertions
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
                problems.append({
                    "code": "invalid_evidence",
                    "message": f"{label} 不是 JSON 对象，已拒绝",
                })
                continue
            doc_id = str(item.get("doc_id") or "").strip()
            locator = str(item.get("locator") or "").strip()
            quote = str(item.get("quote") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            if purpose:
                covered_purposes.add(purpose)
            if not doc_id or not locator or not quote:
                problems.append({
                    "code": "incomplete_evidence",
                    "message": f"{label} 缺少 doc_id／locator／quote，溯源链断开",
                })
                continue
            try:
                source_text = resolve(doc_id, locator)
            except Exception as exc:
                # 评审 C7：基础设施故障与确定性缺口分开——
                # 故障记 verification_error，整体校验状态降为不可信。
                code = "verification_error" if _is_infra_error(exc) else "source_unresolvable"
                problems.append({
                    "code": code,
                    "message": (
                        f"{label} 的 {doc_id}|{locator} 解析权威原文时失败"
                        f"（{type(exc).__name__}：{exc}）"
                    ),
                })
                continue
            if source_text is None:
                problems.append({
                    "code": "source_unresolvable",
                    "message": f"{label} 的 {doc_id}|{locator} 无法解析到原文",
                })
                continue
            offset = source_text.find(quote)
            if offset < 0:
                problems.append({
                    "code": "quote_not_found",
                    "message": f"{label} 的 quote 未在原文中逐字出现：{quote[:60]!r}",
                })
                continue
            if pending_aware:
                delivery = evidence_delivery_for_submit(
                    ledger, doc_id, locator, offset, offset + len(quote),
                )
                if delivery == "pending":
                    problems.append({
                        "code": "pending_delivery",
                        "message": (
                            f"{label} 的片段已取回但尚未经过下一轮消息边界核验；"
                            "请下一轮重新提交完整清单确认"
                        ),
                    })
                    continue
            else:
                delivery = _evidence_delivery(
                    ledger, doc_id, locator, offset, offset + len(quote),
                )
            deliveries.append(delivery)
            if delivery != DELIVERED:
                problems.append({
                    "code": "not_delivered",
                    "message": (
                        f"{label} 的引文区间未被已送达片段完整覆盖"
                        f"（{delivery}）；评审 C1：只读首段不等于整块送达"
                    ),
                })

    required = [
        str(dep) for dep in (conclusion.get("required_dependencies") or [])
    ]
    missing_deps = [dep for dep in required if dep not in covered_purposes]
    if missing_deps:
        problems.append({
            "code": "missing_dependencies",
            "message": "声明的必要依赖未被任何证据用途覆盖：" + "、".join(missing_deps),
        })

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
        codes = sorted({
            str(p.get("code") or "")
            for p in row.get("problems") or []
            if isinstance(p, dict)
        })
        anchor = str(row.get("report_quote") or row.get("text_location") or "").strip()
        where = f"「{anchor[:40]}…」附近" if anchor else "位置未提供"
        lines.append(
            f"> - {row.get('id')}（{where}）：{'、'.join(codes) or '未获完整支持'}",
        )
    head = (
        f"> **证据完整性校验（A4）**：本报告未完全通过结论证据校验"
        f"（状态：{status}）。"
    )
    tail = "> 明细见 corpus/manifest_verification.json。"
    if lines:
        return "\n".join([
            "---", "", head,
            "> 以下结论未获「逐字可溯源且完整送达」的原文支持，请按未校验内容对待：",
            *lines, tail,
        ])
    return "\n".join(["---", "", head, "> 部分结论未获完整证据支持。", tail])


def publish_boundary(
    ledger: ConsumptionLedger,
    *,
    final_text: str,
    answer_status: str,
    directory: Path | None = None,
    resolver: SourceResolver | None = None,
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
        if (not ledger.offered and not ledger.fetched
                and not ledger.semantic.calls and not ledger.semantic.receipts):
            outcome["boundary_action"] = "skip"
            return outcome
        verification = verify_and_record(
            ledger, directory=directory, resolver=resolver, final_text=final_text,
            extra={"boundary_answer_status": answer_status},
        )
        outcome["verification"] = verification
        outcome["publish_status"] = verification.get("status") or ""
        if outcome["publish_status"] == PUBLISH_VERIFIED:
            outcome["boundary_action"] = "publish"
            return outcome
        if not enforcement_enabled():
            return outcome
        outcome["final_text"] = (
            f"{final_text.rstrip()}\n\n{_limitation_block(verification)}"
        )
        if outcome["answer_status"] == "complete":
            outcome["answer_status"] = "partial"
        outcome["boundary_action"] = "downgrade"
        return outcome
    except Exception as exc:
        logger.warning("corpus ledger: 发布边界执行失败（fail-open）：%s", exc)
        outcome["boundary_action"] = "observe"
        return outcome


def evidence_delivery_for_submit(
    ledger: ConsumptionLedger, doc_id: str, locator: str,
    quote_start: int, quote_end: int,
) -> str:
    """环内提交清单用的送达判定：在 :func:`_evidence_delivery` 基础上区分
    「已核验未送达」与「新取片段待边界核验」（评审 C3）。

    返回 ``delivered``／``partial``／``truncated``／``pending``／``not_delivered``：
    新取片段（取回 turn 晚于最近一次消息边界核验）标 ``pending``——它将在本轮
    结束的消息边界被核验，下一轮重新提交即可确认，不诱发无效补取。
    """
    refs = [
        ref for ref in ledger.fetched
        if ref.doc_id == doc_id and ref.locator == locator
    ]
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

    def _get_ledger(self) -> ConsumptionLedger:
        if self._ledger is None:
            self._ledger = get_run_ledger(
                task_id=self._task_id,
                role_id=self._role_id,
                pipeline_id=self._pipeline_id,
            )
        return self._ledger

    async def on_tool_call(
        self, ctx: TurnContext, tool_call: dict,
    ) -> None:
        try:
            name = str(tool_call.get("name") or "")
            if name not in {TOOL_FETCH, SEMANTIC_TOOL}:
                return
            args = tool_call.get("args")
            if isinstance(args, dict):
                if name == SEMANTIC_TOOL:
                    self._get_ledger().semantic.record_call(
                        args, str(tool_call.get("id") or ""), ctx.turn,
                    )
                else:
                    self._get_ledger().record_fetch_call(args, turn=ctx.turn)
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_tool_call: %s", exc)

    async def on_tool_result(
        self, ctx: TurnContext, result: ToolResult,
    ) -> None:
        try:
            name = result.name
            if name == TOOL_SEARCH:
                self._get_ledger().record_search(result.result, turn=ctx.turn)
            elif name == TOOL_FETCH:
                self._get_ledger().record_fetch_result(
                    result.result, is_error=result.is_error, turn=ctx.turn,
                )
            elif name == SEMANTIC_TOOL:
                self._get_ledger().semantic.record_result(
                    result.args, result.result, result.tool_call_id, ctx.turn,
                )
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_tool_result: %s", exc)

    async def on_turn_end(self, ctx: TurnContext) -> None:
        """在每个 turn 结束（下一轮真实模型请求之前）增量核验送达快照。

        评审 C3：环内提交清单需要**及时更新**的 delivered 状态；只在
        ``on_loop_end`` 补账会让新取片段永远 ``unknown``，修正闭环失效。
        只扫本轮新增的消息（``finalize`` 对已 delivered 片段幂等跳过，压缩改写
        历史时按更坏情况整表重扫一次，合并取强不会降级）。
        """
        try:
            ledger = self._get_ledger()
            messages = list(ctx.messages or [])
            start = self._scanned_messages if self._scanned_messages <= len(messages) else 0
            if len(messages) > start:
                ledger.finalize(messages[start:])
            self._scanned_messages = len(messages)
            if ctx.turn > ledger.last_finalized_turn:
                ledger.last_finalized_turn = ctx.turn
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_turn_end: %s", exc)

    async def on_loop_end(self, result: AgentLoopResult) -> None:
        try:
            ledger = self._get_ledger()
            ledger.finalize(result.messages)
            write_ledger(ledger)
            verify_and_record(ledger)
        except Exception as exc:
            logger.warning("ConsumptionLedgerObserver.on_loop_end: %s", exc)


__all__ = [
    "CORPUS_TOOLS",
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
