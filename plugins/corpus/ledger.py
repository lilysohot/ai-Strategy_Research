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

logger = logging.getLogger(__name__)

LEDGER_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
VERIFICATION_SCHEMA_VERSION = 1

# ── 四状态 + 补充词汇 ────────────────────────────────────────────────────
DELIVERED = "delivered"
TRUNCATED = "truncated"
UNKNOWN = "unknown"
SKIPPED = "skipped"

# 结论状态（结论证据充分性）
SUPPORTED = "supported"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"

# 产物发布状态（报告／最终回复）
PUBLISH_VERIFIED = "verified"
PUBLISH_PARTIAL = "partial"
PUBLISH_UNSUPPORTED = "unsupported"
PUBLISH_DRAFT = "draft"

#: 交付状态强弱（合并时取更强，绝不因某一路径看不到而降级）。
_DELIVERY_RANK = {UNKNOWN: 1, TRUNCATED: 2, DELIVERED: 3}

#: 结论证据覆盖（delivered 为最全，unknown 为无法核验）。
_EVIDENCE_RANK = {UNKNOWN: 0, "partial": 1, DELIVERED: 2}

TOOL_SEARCH = "corpus_search"
TOOL_FETCH = "corpus_fetch"
TOOL_INVENTORY = "corpus_inventory"
CORPUS_TOOLS = frozenset({TOOL_SEARCH, TOOL_FETCH, TOOL_INVENTORY})

#: 声明依赖的用途词表（结论证据充分性按用途核对）。
DEPENDENCY_PURPOSES: tuple[str, ...] = (
    "value", "period", "unit", "header", "footnote",
)

#: 判定「截断」所需的最短可辨前缀；片段太短则只记 unknown，不猜截断。
TRUNCATED_MIN_PREFIX = 32

#: run artifacts 相对路径（A4 落盘 = 独立 JSON 工件）。
_ARTIFACT_SUBDIR = "corpus"
LEDGER_FILENAME = "ledger.json"
MANIFEST_FILENAME = "manifest.json"
VERIFICATION_FILENAME = "manifest_verification.json"

_RUN_DIR_ENV = "APODEX_RUN_DIR"

#: 同一 run 共享的账本（子代理与主循环都往里追加）。
_LEDGERS: dict[str, ConsumptionLedger] = {}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _escaped(text: str) -> str:
    """把片段文本转成它在 JSON 字符串里出现的形式（去掉两侧引号）。"""
    return json.dumps(text, ensure_ascii=False)[1:-1]


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
    #: identity -> 片段 JSON 转义文本（仅内存，用于最终消息核验；不落盘）。
    _fragment_text: dict[tuple[str, str, int, int], str] = field(
        default_factory=dict, repr=False,
    )
    _offered_scopes: set[str] = field(default_factory=set, repr=False)

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

    # ── delivered：最终消息边界核验 ────────────────────────────────────
    def finalize(self, messages: list[Message] | None) -> None:
        """在最终消息里核验每个 fetched 片段是否**仍完整存在**。

        比对用片段文本的 JSON 转义形式（消息正文是 ``json.dumps(..., ensure_ascii=False)``
        的结果），既覆盖未截断的合法 JSON，也覆盖被 head-cap 切坏的 JSON。核验不了
        的片段保持 ``unknown``——不推断为已送达。合并只取更强状态。
        """
        blob = _messages_blob(messages)
        for ref in self.fetched:
            text = self._fragment_text.get(ref.identity)
            if text is None:
                continue
            status = _delivery_status(text, blob)
            current = self.delivered.get(ref.identity, UNKNOWN)
            if delivery_rank(status) > delivery_rank(current):
                self.delivered[ref.identity] = status

    def delivered_status(self, identity: tuple[str, str, int, int]) -> str:
        return self.delivered.get(identity, UNKNOWN)

    # ── 范围完整性 ─────────────────────────────────────────────────────
    def range_completeness(self) -> list[dict[str, Any]]:
        """按 offered scope 汇总：必需片段是否全部取回／送达（范围完整性）。"""
        fetched_locators = {ref.locator for ref in self.fetched}
        delivered_locators = {
            ref.locator
            for ref in self.fetched
            if self.delivered_status(ref.identity) == DELIVERED
        }
        out: list[dict[str, Any]] = []
        for scope in self.offered:
            locators = list(scope.get("locators") or [])
            missing = [loc for loc in locators if loc not in fetched_locators]
            undelivered = [loc for loc in locators if loc not in delivered_locators]
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
                # 有未解决错误或跳过 ⇒ 范围不完整。
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
            "offered": self.offered,
            "requested": self.requested,
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
    """读取模型产出的报告证据清单；缺文件返回 ``None``（产物只能标 draft）。"""
    folder = directory or resolve_artifact_dir()
    if folder is None:
        return None
    target = folder / MANIFEST_FILENAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


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
) -> dict[str, Any]:
    """校验清单并落盘验证工件；缺清单则记录 draft。观测层：绝不抛。"""
    folder = directory or resolve_artifact_dir()
    try:
        if manifest is None:
            manifest = load_manifest(directory=folder)
        if manifest is None:
            verification = {
                "schema_version": VERIFICATION_SCHEMA_VERSION,
                "status": PUBLISH_DRAFT,
                "reason": "缺少结论证据清单：产物只能作为草稿，不得标记为已通过证据完整性校验",
                "conclusions": [],
            }
        else:
            verification = verify_manifest(manifest, ledger, resolver=resolver)
    except Exception as exc:
        logger.warning("corpus ledger: 清单校验失败（忽略）：%s", exc)
        return {"schema_version": VERIFICATION_SCHEMA_VERSION, "status": PUBLISH_DRAFT,
                "reason": f"校验异常：{type(exc).__name__}: {exc}", "conclusions": []}
    path = write_verification(verification, directory=folder)
    verification["artifact_path"] = str(path) if path is not None else None
    return verification


# ── 结论证据清单校验 ─────────────────────────────────────────────────────

#: ``(doc_id, locator) -> 权威原文``；返回 ``None`` 表示该来源无法解析。
SourceResolver = Callable[[str, str], "str | None"]


def _default_resolver(doc_id: str, locator: str) -> str | None:
    try:
        from plugins.corpus.service import get_service

        return get_service().fetch_verbatim(doc_id, locator).text
    except Exception:
        return None


def _evidence_delivery(
    ledger: ConsumptionLedger, doc_id: str, locator: str,
) -> str:
    """该 (doc_id, locator) 的原文是否完整送达：delivered／partial／unknown。"""
    refs = [ref for ref in ledger.fetched if ref.doc_id == doc_id and ref.locator == locator]
    if not refs:
        return UNKNOWN
    statuses = [ledger.delivered_status(ref.identity) for ref in refs]
    if all(status == DELIVERED for status in statuses):
        return DELIVERED
    if all(delivery_rank(status) <= delivery_rank(UNKNOWN) for status in statuses):
        return UNKNOWN
    return "partial"


def verify_manifest(
    manifest: dict[str, Any],
    ledger: ConsumptionLedger,
    *,
    resolver: SourceResolver | None = None,
) -> dict[str, Any]:
    """由账本与权威原文**重算**每条结论的状态；不接受模型自报通过。

    每条结论的 ``status``：

    - ``unsupported``：证据缺失、quote 无法溯源（编造）或来源无法解析；
    - ``partial``：quote 可溯源，但原文未完整送达，或声明的必要依赖（期间／单位／
      表头／脚注）未被任何证据用途覆盖；
    - ``supported``：quote 逐字可溯源、原文完整送达、声明依赖全覆盖。
    """
    resolve = resolver or _default_resolver
    conclusions_out: list[dict[str, Any]] = []
    for index, conclusion in enumerate(manifest.get("conclusions") or []):
        if not isinstance(conclusion, dict):
            continue
        conclusions_out.append(
            _verify_conclusion(conclusion, index, ledger, resolve),
        )
    counts = {SUPPORTED: 0, PARTIAL: 0, UNSUPPORTED: 0}
    for row in conclusions_out:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    if not conclusions_out:
        status = PUBLISH_DRAFT
    elif counts[UNSUPPORTED] and counts[UNSUPPORTED] == len(conclusions_out):
        status = PUBLISH_UNSUPPORTED
    elif counts[PARTIAL] or counts[UNSUPPORTED]:
        status = PUBLISH_PARTIAL
    else:
        status = PUBLISH_VERIFIED
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": status,
        "counts": counts,
        "range_completeness": ledger.range_completeness(),
        "all_offered_fetched": ledger.all_offered_fetched(),
        "conclusions": conclusions_out,
    }


def _verify_conclusion(
    conclusion: dict[str, Any],
    index: int,
    ledger: ConsumptionLedger,
    resolve: SourceResolver,
) -> dict[str, Any]:
    cid = str(conclusion.get("id") or f"C{index + 1}")
    evidence = conclusion.get("evidence")
    problems: list[dict[str, str]] = []
    covered_purposes: set[str] = set()
    deliveries: list[str] = []

    if not isinstance(evidence, list) or not evidence:
        problems.append({"code": "no_evidence", "message": "结论未附任何证据"})
    else:
        for ev_index, item in enumerate(evidence):
            if not isinstance(item, dict):
                continue
            label = f"evidence[{ev_index}]"
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
            source_text = resolve(doc_id, locator)
            if source_text is None:
                problems.append({
                    "code": "source_unresolvable",
                    "message": f"{label} 的 {doc_id}|{locator} 无法解析到原文",
                })
                continue
            if quote not in source_text:
                problems.append({
                    "code": "quote_not_found",
                    "message": f"{label} 的 quote 未在原文中逐字出现：{quote[:60]!r}",
                })
                continue
            delivery = _evidence_delivery(ledger, doc_id, locator)
            deliveries.append(delivery)
            if delivery != DELIVERED:
                problems.append({
                    "code": "not_delivered",
                    "message": f"{label} 的原文未完整送达模型（{delivery}）",
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

    unsupported_codes = {"no_evidence", "incomplete_evidence", "source_unresolvable",
                         "quote_not_found"}
    if any(p["code"] in unsupported_codes for p in problems):
        status = UNSUPPORTED
    elif problems:
        status = PARTIAL
    else:
        status = SUPPORTED
    return {
        "id": cid,
        "text_location": str(conclusion.get("text_location") or ""),
        "status": status,
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "covered_purposes": sorted(covered_purposes),
        "missing_dependencies": missing_deps,
        "delivery": sorted(set(deliveries)),
        "problems": problems,
        # 明确忽略模型自报：字段仅记录，不参与判定。
        "model_claimed_complete": conclusion.get("complete"),
    }


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
            if name != TOOL_FETCH:
                return
            args = tool_call.get("args")
            if isinstance(args, dict):
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
        except Exception as exc:
            logger.debug("ConsumptionLedgerObserver.on_tool_result: %s", exc)

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
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "PARTIAL",
    "PUBLISH_DRAFT",
    "PUBLISH_PARTIAL",
    "PUBLISH_UNSUPPORTED",
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
    "evidence_rank",
    "get_run_ledger",
    "load_manifest",
    "reset_run_ledgers",
    "resolve_artifact_dir",
    "run_ledger_key",
    "verify_and_record",
    "verify_manifest",
    "write_ledger",
    "write_verification",
]
