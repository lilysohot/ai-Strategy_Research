"""离线验收：用一次 run 的 fetch 回执重建文档单元，重放 v2 分页并出覆盖映射报告。

不连数据库、不跑 agent，只读 ``<run>/run/corpus/tool-refs`` 与 ``search-refs``：

* 从历史分页回执按 ``unit_id + fragment.start`` 拼回原始单元；
* 用 v2 双预算重放，量真实页数（与轨迹里观测到的 v1 页数对照）；
* 按文档版本原始区间做分母、送达区间并集做分子，出覆盖报告；
* 汇报 ``native1`` → ``document1`` 后台映射的可用情况，查不到就报 unmapped，不猜；
* 用后台映射把「原始检索范围」的送达情况单列成 ``retrieval_scope`` 报告。

后台映射随 ``ledger.json`` 的 ``native_mappings`` 落盘（由 ``corpus_fetch`` 从
``native_slices`` 权威坐标采集）；旧 run 可用 ``--mapping`` 外部补表验收。

用法::

    uv run python scripts/replay_corpus_coverage.py <run-dir> [--text-budget 6000] [--mapping map.json]
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from plugins.corpus.coverage import (
    Delivery,
    NativeMapping,
    UnitRange,
    coverage_report,
    delivered_union,
    map_native_to_document,
    mappings_from_dict,
    merge_intervals,
    native_to_units,
)
from plugins.corpus.cursor import decode_cursor
from plugins.corpus.preparation import document_read, read_pg
from plugins.corpus.tool_refs import resolve_cursor_reference
from plugins.tools import _corpus_document


def _payload(path: Path) -> dict[str, Any] | None:
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    value = body.get("value") if isinstance(body, dict) else None
    payload = value.get("payload") if isinstance(value, dict) else None
    return payload if isinstance(payload, dict) else None


def document_pages(run: Path) -> list[dict[str, Any]]:
    pages = []
    for path in sorted((run / "run" / "corpus" / "tool-refs").glob("*.json")):
        payload = _payload(path)
        if payload and payload.get("scope") == "document" and payload.get("ok"):
            pages.append(payload)
    return pages


def reconstruct_units(pages: list[dict[str, Any]]) -> tuple[list[Any], dict[str, Any]]:
    """按 (unit_id, fragment.start) 去重拼接；整单元优先于分片。"""
    fragments: dict[str, dict[int, str]] = defaultdict(dict)
    whole: dict[str, str] = {}
    meta: dict[str, dict[str, Any]] = {}
    for page in pages:
        for item in page.get("items") or []:
            uid = str(item.get("unit_id") or "")
            if not uid:
                continue
            meta.setdefault(uid, {"kind": item.get("kind"), "page": item.get("page"),
                                  "ocr": item.get("ocr_unverified") or item.get("text_origin") == "ocr",
                                  "status": item.get("status", "kept")})
            fragment = item.get("fragment") or {}
            if fragment:
                fragments[uid][int(fragment.get("start", 0))] = str(item.get("text") or "")
            else:
                whole[uid] = str(item.get("text") or "")
    texts = {}
    for uid, parts in fragments.items():
        if uid in whole:
            texts[uid] = whole[uid]
            continue
        text = ""
        for start in sorted(parts):
            if start > len(text):
                raise ValueError(f"missing source interval: {uid}")
            overlap = min(len(text) - start, len(parts[start]))
            if text[start:start + overlap] != parts[start][:overlap]:
                raise ValueError(f"conflicting source interval: {uid}")
            text += parts[start][overlap:]
        texts[uid] = text
    texts.update({uid: text for uid, text in whole.items() if uid not in texts})
    ordered = sorted(
        texts, key=lambda uid: (int(uid.split(":")[-1]) if uid.split(":")[-1].isdigit() else 0, uid)
    )
    units = [
        document_read.DocumentUnit(
            read_pg.UnitEvidence(uid, texts[uid], meta.get(uid, {}).get("page"),
                                 "local_ocr:replay" if meta.get(uid, {}).get("ocr") else None, ()),
            str(meta.get(uid, {}).get("kind") or "body"),
            str(meta.get(uid, {}).get("status") or "kept"),
        )
        for uid in ordered
    ]
    return units, {"texts": texts, "meta": meta}


class _Service:
    """只读重放：把重建出的单元当成目标文档版本。"""

    def __init__(self, units: list[Any], build_id: str, source_id: str,
                 names: tuple[str, ...] = ()) -> None:
        self.document = document_read.DocumentUnits(source_id, build_id, True, tuple(units), names)

    def document_units(self, doc_id: str) -> Any:
        return self.document


def replay_v2(
    service: _Service, doc_id: str, budget: int, *, processor: Any = None,
    stats: list[dict[str, Any]] | None = None,
) -> tuple[int, list[dict[str, Any]], str | None]:
    cursor: dict[str, Any] | None = None
    items: list[dict[str, Any]] = []
    pages = 0
    while pages < 1000:
        # _Service is a read-only, duck-typed stand-in for the version-bound
        # service; document_page only needs document_units() from it.
        raw = _corpus_document.document_page(cast(Any, service), doc_id, budget, cursor)
        payload = json.loads(raw)
        if not payload.get("ok"):
            return pages, items, str(payload.get("error"))
        pages += 1
        if processor is not None:
            from frontier_agent.core.loop_types import ToolResult
            from plugins.corpus.ledger import ConsumptionLedger

            raw = _corpus_document._json(payload)
            call_id = f"replay-{pages}"
            ledger = ConsumptionLedger()
            ledger.record_fetch_result(raw, tool_call_id=call_id)
            body = processor.process(ToolResult(name="corpus_fetch", args={}, result=raw,
                                     duration_ms=0, is_error=False, tool_call_id=call_id))
            ledger.finalize([{"role": "tool", "tool_call_id": call_id, "content": body}])
            if ledger.responses[0]["delivery_state"] != "delivered":
                return pages, items, str(ledger.responses[0]["delivery_state"])
            if stats is not None:
                stats.append({"visible_chars": len(body), "internal_chars": len(raw),
                              "text_chars": sum(len(i.get("text", "")) for i in payload["items"])})
        items.extend(payload.get("items") or [])
        next_cursor = payload.get("next_cursor")
        if not next_cursor:
            return pages, items, None
        cursor = decode_cursor(resolve_cursor_reference(next_cursor))
    return pages, items, "replay exceeded 1000 pages"


def load_native_mappings(run: Path, supplied: Path | None) -> list[NativeMapping]:
    """读取 run 账本里的后台映射；``--mapping`` 用于外部补表（旧 run 验收）。"""
    rows: list[Any] = []
    ledger_path = run / "run" / "corpus" / "ledger.json"
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text())
        except (OSError, ValueError):
            ledger = None
        if isinstance(ledger, dict):
            rows.extend(ledger.get("native_mappings") or [])
    if supplied is not None:
        try:
            extra = json.loads(supplied.read_text())
        except (OSError, ValueError):
            extra = None
        if isinstance(extra, dict):
            rows.extend(extra.get("native_mappings") or extra.get("mappings") or [])
        elif isinstance(extra, list):
            rows.extend(extra)
    return mappings_from_dict(rows)


def retrieval_scope_coverage(
    mappings: list[NativeMapping],
    deliveries: list[Delivery],
    *,
    doc_id: str,
    expected_locators: list[str] | None = None,
) -> dict[str, Any]:
    """原始检索范围覆盖：分母＝已映射块绑定的权威单元区间，分子＝送达区间与其交集。"""
    union = delivered_union(deliveries, doc_id=doc_id)
    mappings = [m for m in mappings if m.doc_id == doc_id]
    if expected_locators is not None:
        mappings = [m for m in mappings if m.locator in expected_locators]
    mapped = {m.locator for m in mappings}
    unmapped = sorted(set(expected_locators or []) - mapped)
    by_unit: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for mapping in mappings:
        for item in mapping.slices:
            by_unit[_corpus_document.unit_locator(item.unit_id)].append((item.start, item.end))
    denominator = 0
    numerator = 0
    for locator, wanted in by_unit.items():
        target = merge_intervals(wanted)
        denominator += sum(end - start for start, end in target)
        delivered = union.get(locator, [])
        covered = merge_intervals(
            (max(a, c), min(b, d)) for a, b in target for c, d in delivered if a < d and c < b
        )
        numerator += sum(end - start for start, end in covered)
    return {
        "scope": "native_retrieval",
        "mapped_blocks": len(mappings),
        "denominator_chars": denominator,
        "delivered_chars": numerator,
        "ratio": numerator / denominator if denominator else None,
        "ratio_scope": "mapped_intervals_only",
        "unmapped": unmapped,
        "complete": expected_locators is not None and not unmapped and denominator > 0 and numerator >= denominator,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--text-budget", type=int, default=6000)
    parser.add_argument(
        "--mapping",
        type=Path,
        default=None,
        help="外部后台映射表 JSON（list 或 {native_mappings: [...]}），用于旧 run 补表验收",
    )
    args = parser.parse_args()
    run = args.run_dir
    pages = document_pages(run)
    if not pages:
        print(json.dumps({"error": "no document page receipts found", "run": str(run)}))
        return 1
    os.environ.setdefault("CORPUS_TOOL_REF_ROOT", tempfile.mkdtemp(prefix="corpus-replay-"))

    doc_id = str(pages[0]["doc_id"])
    build_id = str(pages[0]["build_id"])
    pages = [p for p in pages if p.get("doc_id") == doc_id and p.get("build_id") == build_id]
    source_id = str(pages[0].get("source_id") or "")
    units, _ = reconstruct_units(pages)
    declared_units = max(int(p.get("total_units") or 0) for p in pages)
    if len(units) != declared_units:
        raise ValueError("Incomplete historical source reconstruction; coverage denominator unavailable")
    service = _Service(units, build_id, source_id, tuple(pages[0].get("original_names") or ()))

    from workflows.agent_team.subagent_runtime import SwarmToolResultPostProcessor
    from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor

    os.environ["CORPUS_NAVIGATION_MODE"] = "on"
    stats: list[dict[str, Any]] = []
    page_count, items, error = replay_v2(service, doc_id, args.text_budget,
                                      processor=ReactToolResultPostProcessor(), stats=stats)
    team_count, team_items, team_error = replay_v2(service, doc_id, args.text_budget,
                                                processor=SwarmToolResultPostProcessor())
    if (team_count, team_items, team_error) != (page_count, items, error):
        raise ValueError("React and team delivery disagree")
    deliveries = [
        Delivery(
            doc_id=doc_id,
            locator=str(item["locator"]),
            start=int((item.get("fragment") or {}).get("start", 0)),
            end=int((item.get("fragment") or {}).get("end", len(str(item.get("text") or "")))),
        )
        for item in items
        if item.get("locator")
    ]
    unit_ranges = [
        UnitRange(
            locator=_corpus_document.unit_locator(unit.unit.unit_id),
            unit_id=unit.unit.unit_id,
            chars=len(unit.unit.raw_text),
        )
        for unit in units
    ]
    report = coverage_report(
        doc_id=doc_id,
        units=unit_ranges,
        deliveries=deliveries,
        page_count=page_count,
    )

    # native1 → document1：查不到后台映射就如实报 unmapped，绝不按序号猜。
    native: list[str] = []
    for path in sorted((run / "run" / "corpus" / "search-refs").glob("*.json")):
        try:
            ref = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        hit = ref.get("hit") if isinstance(ref, dict) else None
        if not isinstance(hit, dict) or hit.get("doc_id") != doc_id:
            continue
        for locator in hit.get("context_locators") or []:
            native.append(str(locator))
    native = list(dict.fromkeys(native))
    # 后台映射只查表，绝不按序号／名称猜。新 run 由 corpus_fetch 在取 native1
    # 句柄时把 native_slices 权威坐标写进 ledger.json；旧 run 可用 --mapping 补表。
    mappings = load_native_mappings(run, args.mapping)
    known_units = {unit.unit_id: unit for unit in unit_ranges}
    mapping = map_native_to_document(
        native,
        native_to_units=native_to_units(mappings),
        known_units=known_units,
    )
    if args.mapping is not None and mappings:
        mapping["note"] = (
            f"外部补表 {args.mapping} 提供 {len(mappings)} 条映射，仅用于验收重放，"
            "不写回 run 产物；只查表不推断。"
        )
    elif mappings:
        mapping["note"] = (
            f"ledger.json 后台映射表 {len(mappings)} 条，来自 native_slices 权威坐标，"
            "只查表不推断。"
        )
    else:
        mapping["note"] = (
            "该 run 的 ledger.json 未含 native_mappings（旧 run，或全程只走 document1 分页）；"
            "检索块如实报 unmapped。新 run 取 native1 句柄时自动落盘，也可用 --mapping 外部补表。"
        )
    scope = retrieval_scope_coverage(mappings, deliveries, doc_id=doc_id, expected_locators=native)
    print(
        json.dumps(
            {
                "run": str(run),
                "observed_v1_page_count": len(pages),
                "replayed_v2_page_count": page_count,
                "replay_error": error,
                "verified_boundaries": ["react_final_message", "team_final_message", "ledger_delivery"],
                "page_metrics": stats,
                "reconstructed_units": len(units),
                "declared_total_units": max(
                    (int(p.get("total_units") or 0) for p in pages), default=0
                ),
                "text_budget": args.text_budget,
                "coverage": report,
                "retrieval_scope": scope,
                "native_document_mapping": mapping,
                "source_extraction": "unknown (not inferred from ingested-text coverage)",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
