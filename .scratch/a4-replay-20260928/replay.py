"""A4 固定任务回放（隔离库检索档）：30 道冻结题、零模型、PG 只读。

目的：在真实注册工具上跑固定任务集，采集 A4 账本的 offered／requested／fetched／
delivered 四集合与成本指标（调用数、分页数、重复补取、输入 token 代理、延迟），并与
历史 75c6 基线（36 offered／10 fetched）对照。按文档 §2「三类结果分开报告」，本档是
**隔离语料库回放**：不调模型；delivered 用**真实工作流后处理链**
（`check_aggregate_budget` → `ReactToolResultPostProcessor.process` →
`_with_recovery_handle` → `tool_msg`）在最终消息边界核验，而不是猜。

只读保证：``PGOPTIONS`` 强制 ``default_transaction_read_only=on``，并在连接上断言
``transaction_read_only=on`` 与 ``current_database()=postgres``。零模型保证：import 陷阱
拒绝 ``openai``／``anthropic`` 及语义模型模块。

选题、问题文本来自冻结件；采集只用问题文本，**不用 gold** 决定取哪些块（读全部
offered 上下文，与 ``tools/corpus_product_observations.py`` 同口径）。A2 的分页信封
需要跟随 ``next_cursor`` 才算取全，这里如实跟随并计入成本。

本脚本同时把四个「消费侧接缝」缺陷记录成数据（不是断言，是可复算的计数）：

1. **搜索信封被按字符硬切**——已修（D1）：``corpus_search`` 纳入
   ``structured_result_fit`` 分派（``fit_search_payload``：超限先去诊断字段、再按
   相关度**整条**舍弃尾部命中并标 ``hits_elided``，绝不硬切），并在两个后处理器里
   给了有界预算 20000（覆盖实测最大体 18.6K）。期望 ``search_envelope_broken=0``。
2. **分页信封丢失单元级证据**——**未修（D2，方向待定）**：``corpus_fetch`` 超限转
   分页信封后，item 不含 ``source_id``／``semantic_cells``，``units`` 只有
   ``page``＋``unit_id``；行／列（row/col）证据在分页路径上不可恢复，既有消费者
   （``tools/corpus_product_observations.py``）与产品门因此失效。
3. **固定字段撑爆预算**——已修（D3）：``corpus_fetch._page`` 在 full 视图的 units
   清单独占 ``max_chars`` 时**自动改用 compact 视图重试一次**（item 标
   ``view_fallback``），不再让调用方自己领会；compact 仍装不下才报错，且提示换成
   真能执行的退路。期望 ``incomplete_locators=0``、``compact_fallback_items>0``。
4. **分页信封被当单块结果压缩（D4）**——已修：分页信封同样以 ``ok: true`` 开头，
   曾被 ``fit_structured_payload`` 当成单块结果交给 ``_compact_payload``，``items``
   （正文＋句柄＋游标）整个丢失，正文静默消失（delivered 核验不到即计
   ``unknown``）。修复后按 ``items`` 判形，信封只去诊断性的 ``units``、保留正文与
   ``next_cursor``；期望 ``unknown=0``、``delivered=fetched_fragments``。

另有一个**次级问题（未修，方向待定）**：``_page`` 的片段预算按**原始字符数**算，而
信封序列化后换行转义为两字符；正文含较多换行时信封会略超自身 ``max_chars``
（实测超约 0.6%）。当前靠 D4 的防御性压缩兜住，无数据丢失，仅丢 ``units`` 诊断字段。
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.abc
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
RUN_75C6 = ROOT / ".apodex/runs/20260925-182401+0800-react-75c6"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import dotenv_values  # noqa: E402

_config = dotenv_values(ROOT / ".env")
for _key, _value in _config.items():
    if _key.startswith("CORPUS_") and _value is not None:
        os.environ.setdefault(_key, _value)
os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=30000"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

MAX_PAGES_PER_LOCATOR = 20


class DenyModels(importlib.abc.MetaPathFinder):
    """零模型档：任何 LLM SDK／语义模型模块都不允许被 import。"""

    _DENIED_ROOTS = {"openai", "anthropic"}
    _DENIED_PREFIXES = ("plugins.corpus.material_semantics", "plugins.corpus._r2_")

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001, ANN201
        if fullname.split(".")[0] in self._DENIED_ROOTS or fullname.startswith(
            self._DENIED_PREFIXES
        ):
            raise RuntimeError(f"Model module forbidden during A4 replay: {fullname}")
        return None


sys.meta_path.insert(0, DenyModels())

import psycopg  # noqa: E402

from frontier_agent.core.loop_types import ToolResult  # noqa: E402
from frontier_agent.core.runtime.loop.agent_loop import _with_recovery_handle  # noqa: E402
from frontier_agent.utils.tokens import estimate_text_tokens  # noqa: E402
from plugins.corpus.ledger import (  # noqa: E402
    DELIVERED,
    TRUNCATED,
    UNKNOWN,
    ConsumptionLedger,
)
from plugins.corpus.preparation.pg_target import resolve_target_db  # noqa: E402
from plugins.corpus.service import dsn  # noqa: E402
from plugins.tools import get_builtin_tools  # noqa: E402
from plugins.tools._overflow import (  # noqa: E402
    MAX_AGGREGATE_RESULT_CHARS,
    check_aggregate_budget,
)
from workflows.stateful_react_agent._runtime import (  # noqa: E402
    ReactToolResultPostProcessor,
)

SCORING_INPUT = BASE / "i3-2/query-gold-scoring-v1.jsonl"


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_only_probe() -> dict:
    """只读断言 + 语料库规模；任何写能力都判失败。"""
    with psycopg.connect(dsn()) as conn:
        read_only = conn.execute("SHOW transaction_read_only").fetchone()[0]
        database = conn.execute("SELECT current_database()").fetchone()[0]
        assert read_only == "on", f"transaction_read_only={read_only!r}"
        assert database == "postgres", f"current_database={database!r}"
        chunks = conn.execute("SELECT count(*) FROM corpus.corpus_chunks").fetchone()[0]
        builds = conn.execute("SELECT count(*) FROM corpus.corpus_builds").fetchone()[0]
    return {
        "transaction_read_only": read_only,
        "current_database": database,
        "corpus_chunks": int(chunks),
        "corpus_builds": int(builds),
        "aggregate_budget_chars": MAX_AGGREGATE_RESULT_CHARS,
    }


def load_questions() -> list[dict]:
    rows = [
        json.loads(line)
        for line in SCORING_INPUT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [
        {
            "query_id": row["query_id"],
            "question": row["question"],
            "answer_existence": row.get("answer_existence"),
        }
        for row in rows
    ]


class RecordingTool:
    """透明代理：记录原始 args／result（供账本与送达模拟），再委托真实工具。"""

    def __init__(self, name: str, inner, ledger: ConsumptionLedger, sink: list) -> None:
        self.name = name
        self._inner = inner
        self._ledger = ledger
        self._sink = sink
        self._turn = 0

    async def ainvoke(self, args: dict) -> str:
        self._turn += 1
        if self.name == "corpus_fetch":
            self._ledger.record_fetch_call(args, turn=self._turn)
        raw = await self._inner.ainvoke(args)
        self._sink.append({"tool": self.name, "args": dict(args), "raw": raw})
        if self.name == "corpus_search":
            self._ledger.record_search(raw, turn=self._turn)
        elif self.name == "corpus_fetch":
            self._ledger.record_fetch_result(raw, turn=self._turn)
        return raw


def simulate_delivery(
    ledger: ConsumptionLedger, sink: list, processor, *, enabled: bool
) -> dict:
    """在**最终消息组装边界**核验 delivered，忠实复现工作流后处理链。

    链路（``tool_exec.py::_apply_aggregate_budget`` → ``agent_loop.py``）：
    单轮聚合预算 → 每工具后处理 → 恢复句柄 → tool_msg。回放按顺序取证，每个调用
    独立成轮，并如实记录聚合档是否被触发。
    """
    messages = []
    aggregate_triggered = 0
    per_tool: dict[str, dict[str, int]] = {}
    for index, record in enumerate(sink):
        name, raw = record["tool"], record["raw"]
        body = raw
        adjusted = check_aggregate_budget([raw], [name])
        if adjusted[0] != raw:
            aggregate_triggered += 1
            body = adjusted[0]
        result = ToolResult(
            name=name,
            args=record["args"],
            result=body,
            duration_ms=0,
            tool_call_id=f"call-{index}",
            is_error=False,
        )
        processed = processor.process(result)
        final = _with_recovery_handle(processed, result, index, enabled=enabled)
        messages.append({"role": "tool", "content": final, "tool_call_id": result.tool_call_id})
        stats = per_tool.setdefault(
            name, {"calls": 0, "cut": 0, "raw_chars": 0, "final_chars": 0}
        )
        stats["calls"] += 1
        stats["raw_chars"] += len(raw)
        stats["final_chars"] += len(final)
        if len(final) < len(raw):
            stats["cut"] += 1
    ledger.finalize(messages)
    return {
        "messages": messages,
        "aggregate_triggered": aggregate_triggered,
        "per_tool": per_tool,
    }


def valid_json(text: str) -> bool:
    try:
        json.loads(text)
    except (TypeError, ValueError):
        return False
    return True


def _has_cell_evidence(payload: dict) -> bool:
    """该响应是否带行／列（row/col）单元证据。"""
    if payload.get("semantic_cells"):
        return True
    return any(item.get("semantic_cells") for item in payload.get("items") or [])


async def collect_question(
    fetch, doc_id: str, locators: list[str]
) -> dict:
    """对给定 locator 取全：跟随 ``next_cursor`` 直到 ``fetch_complete``。

    返回分页统计（每 locator 调用数、是否取全、信封／单块形状、单元级字段是否保留）。
    """
    pages_per_locator: dict[str, int] = {}
    incomplete: list[str] = []
    envelope_locators: list[str] = []
    legacy_locators: list[str] = []
    cell_evidence_bearing = 0
    compact_fallback_items = 0
    for locator in locators:
        args: dict = {"doc_id": doc_id, "locator": locator}
        pages = 0
        complete = False
        while pages < MAX_PAGES_PER_LOCATOR:
            raw = await fetch.ainvoke(args)
            payload = json.loads(raw) if valid_json(raw) else {}
            pages += 1
            if not payload.get("ok"):
                break
            if "items" in payload:
                if locator not in envelope_locators:
                    envelope_locators.append(locator)
            elif locator not in legacy_locators:
                legacy_locators.append(locator)
            if _has_cell_evidence(payload):
                cell_evidence_bearing += 1
            compact_fallback_items += sum(
                1
                for item in (payload.get("items") or [])
                if item.get("view_fallback") == "compact"
            )
            cursor = payload.get("next_cursor")
            if not cursor:
                complete = True
                break
            args = {"doc_id": doc_id, "cursor": cursor}
        pages_per_locator[locator] = pages
        if not complete:
            incomplete.append(locator)
    return {
        "locators": len(locators),
        "pages": sum(pages_per_locator.values()),
        "pages_per_locator_max": max(pages_per_locator.values(), default=0),
        "multi_page_locators": sum(1 for value in pages_per_locator.values() if value > 1),
        "incomplete_locators": incomplete,
        "envelope_locators": len(envelope_locators),
        "legacy_locators": len(legacy_locators),
        "cell_evidence_bearing": cell_evidence_bearing,
        "compact_fallback_items": compact_fallback_items,
    }


def ledger_stats(ledger: ConsumptionLedger, ledger_dict: dict) -> dict:
    delivered = {DELIVERED: 0, TRUNCATED: 0, UNKNOWN: 0}
    for ref in ledger.fetched:
        status = ledger.delivered_status(ref.identity)
        delivered[status] = delivered.get(status, 0) + 1
    requested_pairs = [
        (row["doc_id"], locator)
        for row in ledger.requested
        for locator in row["locators"]
    ]
    return {
        "duplicate_fetches": len(requested_pairs) - len(set(requested_pairs)),
        "offered_scopes": len(ledger.offered),
        "offered_locators": sum(len(scope["locators"]) for scope in ledger.offered),
        "offered_by_kind": _sum_kinds(ledger.offered),
        "requested_rows": len(ledger.requested),
        "fetched_fragments": len(ledger.fetched),
        "delivered": delivered[DELIVERED],
        "truncated": delivered[TRUNCATED],
        "unknown": delivered[UNKNOWN],
        "errors": len(ledger.errors),
        "skipped": len(ledger.skipped),
        "all_offered_fetched": ledger_dict["all_offered_fetched"],
    }


def _sum_kinds(offered: list) -> dict[str, int]:
    out: dict[str, int] = {}
    for scope in offered:
        for kind, count in (scope.get("by_kind") or {}).items():
            out[kind] = out.get(kind, 0) + int(count)
    return out


def summarize(rows: list[dict], key: str, *, digits: int = 1) -> dict:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "sum": round(sum(values), digits),
        "median": round(statistics.median(values), digits),
        "max": round(max(values), digits),
    }


async def main() -> None:
    probe = read_only_probe()
    registry = get_builtin_tools()
    enabled_recover = "recover_result" in registry
    processor = ReactToolResultPostProcessor()
    questions = load_questions()

    rows: list[dict] = []
    for item in questions:
        ledger = ConsumptionLedger(
            task_id=item["query_id"], role_id="a4-replay", pipeline_id="retrieval-replay"
        )
        sink: list[dict] = []
        search = RecordingTool("corpus_search", registry["corpus_search"], ledger, sink)
        fetch = RecordingTool("corpus_fetch", registry["corpus_fetch"], ledger, sink)
        started = time.perf_counter()
        raw_search = await search.ainvoke({"query": item["question"], "limit": 10})
        search_payload = json.loads(raw_search) if valid_json(raw_search) else {}
        hits = search_payload.get("hits") or []
        paging = {"locators": 0, "pages": 0, "pages_per_locator_max": 0,
                  "multi_page_locators": 0, "incomplete_locators": [],
                  "envelope_locators": 0, "legacy_locators": 0,
                  "cell_evidence_bearing": 0, "compact_fallback_items": 0}
        for hit in hits:
            doc_id = str(hit.get("doc_id") or "")
            locators = list(dict.fromkeys(str(x) for x in (hit.get("context_locators") or [])))
            if not locators:
                continue
            part = await collect_question(fetch, doc_id, locators)
            for key in ("locators", "pages", "multi_page_locators", "envelope_locators",
                        "legacy_locators", "cell_evidence_bearing",
                        "compact_fallback_items"):
                paging[key] += part[key]
            paging["pages_per_locator_max"] = max(
                paging["pages_per_locator_max"], part["pages_per_locator_max"]
            )
            paging["incomplete_locators"] += part["incomplete_locators"]
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        delivery = simulate_delivery(ledger, sink, processor, enabled=enabled_recover)
        ledger_dict = ledger.to_dict()
        search_messages = [
            m["content"] for m, record in zip(delivery["messages"], sink)
            if record["tool"] == "corpus_search"
        ]
        row = {
            "query_id": item["query_id"],
            "answer_existence": item["answer_existence"],
            "hits": len(hits),
            "latency_ms": latency_ms,
            "raw_chars": sum(len(record["raw"]) for record in sink),
            "final_chars": sum(len(m["content"]) for m in delivery["messages"]),
            "final_tokens_estimate": estimate_text_tokens(
                "\n".join(m["content"] for m in delivery["messages"])
            ),
            "aggregate_triggered": delivery["aggregate_triggered"],
            "per_tool": delivery["per_tool"],
            "search_raw_chars": len(raw_search),
            "search_final_chars": len(search_messages[0]) if search_messages else 0,
            "search_envelope_valid_json": (
                valid_json(search_messages[0]) if search_messages else None
            ),
            **paging,
            **ledger_stats(ledger, ledger_dict),
        }
        rows.append(row)

    with_hits = [row for row in rows if row["hits"] > 0]
    totals = {
        "questions": len(rows),
        "questions_with_hits": len(with_hits),
        "offered_locators": sum(row["offered_locators"] for row in rows),
        "fetch_calls": sum(row["per_tool"].get("corpus_fetch", {}).get("calls", 0) for row in rows),
        "pages": sum(row["pages"] for row in rows),
        "multi_page_locators": sum(row["multi_page_locators"] for row in rows),
        "incomplete_locators": sum(len(row["incomplete_locators"]) for row in rows),
        "fetched_fragments": sum(row["fetched_fragments"] for row in rows),
        "delivered": sum(row["delivered"] for row in rows),
        "truncated": sum(row["truncated"] for row in rows),
        "unknown": sum(row["unknown"] for row in rows),
        "duplicate_fetches": sum(row["duplicate_fetches"] for row in rows),
        "errors": sum(row["errors"] for row in rows),
        "skipped": sum(row["skipped"] for row in rows),
        "compact_fallback_items": sum(row["compact_fallback_items"] for row in rows),
        "aggregate_triggered": sum(row["aggregate_triggered"] for row in rows),
        "raw_chars": sum(row["raw_chars"] for row in rows),
        "final_chars": sum(row["final_chars"] for row in rows),
        "final_tokens_estimate": sum(row["final_tokens_estimate"] for row in rows),
        "questions_all_offered_fetched": sum(
            1 for row in rows if row["all_offered_fetched"] is True
        ),
        "questions_search_envelope_broken": sum(
            1 for row in rows if row["search_envelope_valid_json"] is False
        ),
        "questions_search_envelope_broken_of_with_hits": sum(
            1 for row in with_hits if row["search_envelope_valid_json"] is False
        ),
    }
    result = {
        "artifact": "a4-replay",
        "version": 4,
        "generated_at": now(),
        "scope": "isolated-corpus retrieval replay (zero model, read-only PG)",
        "probe": probe,
        "post_processor": {"recover_handle_enabled": enabled_recover},
        "policy": {
            "questions": str(SCORING_INPUT.relative_to(ROOT)),
            "fetch_policy": "read every offered context_locator, follow next_cursor to fetch_complete",
            "max_pages_per_locator": MAX_PAGES_PER_LOCATOR,
        },
        "baseline_75c6": {
            "run": str(RUN_75C6.relative_to(ROOT)),
            "offered": 36,
            "fetched": 10,
            "all_returned_context_fetched": False,
        },
        "findings": {
            "d1_search_envelope_hard_cut": {
                "status": "fixed",
                "tool": "corpus_search",
                "budget": ReactToolResultPostProcessor._BUDGETS["corpus_search"],
                "structured_fit_covered": True,
                "broken_of_questions_with_hits": totals[
                    "questions_search_envelope_broken_of_with_hits"
                ],
                "total_with_hits": len(with_hits),
                "note": "期望 broken=0：超限时按协议压缩（整条舍弃尾部命中）而非硬切。",
            },
            "d2_paging_envelope_drops_cell_evidence": {
                "status": "open",
                "item_keys_sample": [
                    "build_id", "chunk_id", "content_role", "fragment", "kind",
                    "locator", "pages", "relation_status", "relations",
                    "structure_status", "text", "text_chars", "text_sha256", "units",
                ],
                "unit_keys_sample": ["page", "unit_id"],
                "cell_evidence_bearing_calls": sum(
                    row["cell_evidence_bearing"] for row in rows
                ),
                "legacy_shaped_locators": sum(row["legacy_locators"] for row in rows),
                "envelope_shaped_locators": sum(row["envelope_locators"] for row in rows),
                "note": "分页信封不含 source_id／semantic_cells，units 无 row/col；"
                        "行／列证据在分页路径不可恢复，产品门 qp/ep 当前不可执行",
            },
            "d3_fixed_fields_over_budget": {
                "status": "fixed",
                "compact_fallback_items": totals["compact_fallback_items"],
                "incomplete_locators": totals["incomplete_locators"],
                "note": "期望 incomplete=0 且 fallback>0：full 装不下时自动改用 compact 重试。",
            },
            "d4_page_envelope_mangled_as_single_block": {
                "status": "fixed",
                "unknown": totals["unknown"],
                "delivered": totals["delivered"],
                "fetched_fragments": totals["fetched_fragments"],
                "note": "A2 分页信封同样以 ok:true 开头，曾被 fit_structured_payload 当成单块结果"
                        "交给 _compact_payload，items 整个丢失→正文静默消失（计 unknown）。"
                        "修复：按 items 判形，信封只去 units、保留正文与 next_cursor；"
                        "期望 unknown=0 且 delivered=fetched_fragments。",
            },
            "secondary_page_escape_length_accounting": {
                "status": "open",
                "evidence_locator": "chunk:58735cff57d8d456:body:0005",
                "note": "_page 的片段预算按**原始字符数**算，而信封序列化后换行转义为两字符，"
                        "正文含 ~77 个换行时信封实测超自身 max_chars 约 37 字符（0.6%），"
                        "_MARGIN=64 不足覆盖。当前靠 D4 的防御性压缩兜住（无数据丢失，"
                        "仅丢 units 诊断字段）；方向待定：是否改按序列化转义后长度记账。",
            },
        },
        "totals": totals,
        "distribution": {
            "fetch_calls": summarize(
                [{"v": row["per_tool"].get("corpus_fetch", {}).get("calls", 0)} for row in rows], "v"
            ),
            "pages": summarize(rows, "pages"),
            "offered_locators": summarize(rows, "offered_locators"),
            "final_tokens_estimate": summarize(rows, "final_tokens_estimate", digits=0),
            "latency_ms": summarize(rows, "latency_ms", digits=0),
        },
        "per_question": rows,
    }
    (OUT / "replay.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(
            dsn(), "<REDACTED>"
        )
    )
    print(json.dumps({"probe": probe, "totals": totals}, ensure_ascii=False, indent=2))
    print("models_absent", not any(x in sys.modules for x in ["openai", "anthropic"]))


if __name__ == "__main__":
    print("resolved_target", resolve_target_db())
    print("sha256", hashlib.sha256(SCORING_INPUT.read_bytes()).hexdigest()[:16])
    asyncio.run(main())
