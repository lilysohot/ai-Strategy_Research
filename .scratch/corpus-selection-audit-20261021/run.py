"""Capture once with --capture; replay saved candidates without API/PG calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.preparation.selection import SelectedBand
from plugins.corpus.retrieval.diagnostics import (
    RetrievalTrace,
    candidate_fates,
    relevance_bands,
)

MANIFEST = ROOT / ".scratch/corpus-vector-acceptance-20261020/manifest.json"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def restore(data):
    trace = RetrievalTrace()
    for name in ("lexical", "dense", "fused", "selected"):
        values = []
        for row in data[name]:
            row = dict(row)
            for key in ("section_path", "unit_refs", "cells", "label_path", "context_chunk_ids"):
                row[key] = tuple(tuple(v) if isinstance(v, list) else v for v in row[key])
            values.append(SearchHit(**row))
        setattr(trace, name, tuple(values))
    trace.chunk_order = {key: tuple(value) for key, value in data["chunk_order"].items()}
    trace.selectable_bands = tuple(
        SelectedBand(**{**row, "pool": tuple(row["pool"])}) for row in data["selectable_bands"]
    )
    trace.status = data["status"]
    trace.source_limit = data["source_limit"]
    return trace


def baseline_bands(trace, *, round_robin, limit=10):
    """Replay exact production bands before table-header enrichment."""
    by_key = {(h.build_id, h.chunk_id): h for h in trace.fused}
    bands = list(trace.selectable_bands)
    if round_robin:
        sources = list(dict.fromkeys(b.source_id for b in bands))
        grouped = {s: [b for b in bands if b.source_id == s] for s in sources}
        bands = [
            grouped[s][i]
            for i in range(max((len(v) for v in grouped.values()), default=0))
            for s in sources if i < len(grouped[s])
        ]
    output = []
    for band in bands[:limit]:
        ordered = trace.chunk_order[band.source_id]
        anchors = [
            by_key[(band.build_id, ordered[p])]
            for p in band.pool
            if (band.build_id, ordered[p]) in by_key
        ]
        anchor = max(anchors, key=lambda h: (h.score, h.chunk_id))
        output.append(replace(anchor, context_chunk_ids=ordered[band.start : band.end + 1]))
    return tuple(output)


def keys(hits):
    return {(h.build_id, c) for h in hits for c in (h.context_chunk_ids or (h.chunk_id,))}


def metrics(hits, case):
    gold = {(case.get("build_id"), c) for c in case.get("gold_chunks", [])}
    ranks = [i + 1 for i, h in enumerate(hits) if keys((h,)) & gold]
    widths = [len(h.context_chunk_ids or (h.chunk_id,)) for h in hits]
    return {
        "anchor_rank": min(ranks) if ranks else None,
        "returned_bands": len(hits),
        "sources": len({h.source_id for h in hits}),
        "unique_context_chunks": len(keys(hits)),
        "repeated_context_chunks": sum(widths) - len(keys(hits)),
    }


def render_returned(case, capture):
    """Display saved production output first, never promote a delta to evidence."""
    path = HERE / "returned-text" / (case["id"] + ".json")
    if not path.exists():
        return [
            "原文尚未取回：请先运行 fetch_returned.py；不能用以下差异摘要判断可回答性。",
            "",
        ]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["manifest_sha256"] == capture["manifest_sha256"]
    chunks = saved["chunks"]
    full = [f"# {case['id']} 实际返回锚点原文", "", case["question"], "",
            "以下按原捕获顺序展示，没有按答案重排。每个锚点为 fetch_verbatim 的完整原文；"
            "返回区间内其他块未全部展开，完整 locator 列于 captures 中。", ""]
    preview = []
    shown = set()
    for rank, hit in enumerate(capture["public_hits"], 1):
        chunk = chunks[hit["chunk_id"]]
        assert (chunk["build_id"], chunk["source_id"]) == (hit["build_id"], hit["source_id"])
        pages = sorted({u["page"] for u in chunk["units"] if u["page"] is not None})
        block = [
            f"### 实际返回第 {rank} 位：{hit['chunk_id']}", "",
            f"来源：{hit['source_id']}；页码：{pages or '未知'}",
            f"版本句柄：{hit['doc_id']}；定位：{hit['locator']}", "",
            "原搜索摘要（仅用于定位）：", "",
            "> " + hit["snippet"].replace("\n", "\n> "), "",
            "取回的完整锚点原文：", "",
            "> " + chunk["text"].replace("\n", "\n> "), "",
        ]
        full.extend(block)
        shown.add(hit["chunk_id"])
        if rank == 1:
            preview.extend(block)
    # Existing labels are only an audit aid; require actual scope membership.
    for gold in case.get("gold_chunks", []):
        if gold not in chunks or gold in shown:
            continue
        ranks = [
            i + 1 for i, h in enumerate(capture["public_hits"])
            if h["build_id"] == case.get("build_id") and "chunk:" + gold in h["context_locators"]
        ]
        assert ranks, "Label outside actual delivered scope"
        full.extend([
            f"### 原题已有定位标注：{gold}（实际返回区间 {ranks} 内）", "",
            "> " + chunks[gold]["text"].replace("\n", "\n> "), "",
        ])
    link = f"returned-text/{case['id']}.md"
    (HERE / link).write_text("\n".join(full), encoding="utf-8")
    preview.extend([
        f"[查看本题全部 {len(capture['public_hits'])} 个实际返回锚点及完整原文]({link})", "",
        "下方是候选差异诊断；新增、移出和向量独有均不等于可回答证据。", "",
    ])
    return preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    if args.capture:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        os.environ["CORPUS_VECTOR_INPUT_VARIANT"] = "published-search-text-v1"
        os.environ["CORPUS_RETRIEVAL_MODE"] = "hybrid"
        from plugins.corpus.retrieval.cli import pilot_dsn
        from plugins.corpus.retrieval.embedding import VectorConfig
        from plugins.corpus.retrieval.index_pg import VectorIndex
        from plugins.corpus.service import CorpusService
        config = VectorConfig.from_env()
        target = pilot_dsn(config)
        index = VectorIndex(target, config)
        before = index.status()
        if before["active_chunks"] != before["ready_chunks"]:
            raise RuntimeError("baseline_index_incomplete")
        service = CorpusService(target)
        for case in cases:
            path = HERE / "captures" / (case["id"] + ".json")
            if path.exists():
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved["manifest_sha256"] != manifest_hash or saved["profile"] != config.profile:
                    raise RuntimeError("capture_identity_mismatch")
                continue  # Including failures: never silently retry a paid query.
            trace = RetrievalTrace()
            start = time.monotonic()
            hits, coverage = service.search_with_coverage(case["question"], limit=10, trace=trace)
            save(path, {
                "manifest_sha256": manifest_hash,
                "profile": config.profile,
                "case": case["id"],
                "elapsed_ms": (time.monotonic() - start) * 1000,
                "coverage": coverage,
                "trace": trace.as_dict(),
                "public_hits": [asdict(h) for h in hits],
            })
            print(case["id"], trace.status, len(trace.fused), flush=True)
        save(HERE / "index-status.json", {"before": before, "after": index.status()})

    rows = []
    captures = []
    report = [
        "# 检索选择层对照",
        "",
        "沿用原 32 题，不评判研报结论。所有变体复用每题同一次候选快照。",
        "候选池外的证据不可由本记录推断；新增片段未经逐条相关性标注。",
        "source_first 仅改变轮流返回；global_rrf_cap3 同时改变融合与选择，不能单独归因。",
        "各方案最多 10 个区间，但区间长度不同，另行报告上下文块数。",
        "三组统一比较表头补充之前的选择结果；实际服务输出单独保存在 captures 中。",
        "修订：每题先展示真实返回第 1 位的完整锚点原文，并链接全部返回锚点。"
        "此前仅展示差异摘要，遗漏了共同命中的核心证据；旧展示不能用于判断可回答性。",
        "",
    ]
    for case in cases:
        path = HERE / "captures" / (case["id"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["manifest_sha256"] != manifest_hash:
            raise RuntimeError("manifest_changed")
        captures.append(saved)
        trace = restore(saved["trace"])
        report.extend([f"## {case['id']}：{case['question']}", ""])
        report.extend(render_returned(case, saved))
        if trace.status != "hybrid":
            report.extend(["本题向量请求降级，展示实际词法返回，不纳入混合策略对照。", ""])
            rows.append({"case": case["id"], "kind": case["kind"], "excluded": trace.status})
            continue
        baseline = baseline_bands(trace, round_robin=True)
        assert [(h.build_id, h.chunk_id) for h in baseline] == [
            (h.build_id, h.chunk_id) for h in trace.selected
        ], "baseline replay anchors differ from production"
        assert keys(baseline) <= keys(trace.selected), "unexpected service context removal"
        variants = {
            "baseline": baseline,
            "source_first": baseline_bands(trace, round_robin=False),
            "global_rrf_cap3": relevance_bands(trace, source_cap=3),
        }
        baseline_keys = keys(baseline)
        gold = {(case.get("build_id"), c) for c in case.get("gold_chunks", [])}
        pools = {
            name: {(h.build_id, h.chunk_id) for h in getattr(trace, name)}
            for name in ("lexical", "dense", "fused")
        }
        result = {
            "case": case["id"], "kind": case["kind"],
            "candidate_gold": {name: bool(pool & gold) for name, pool in pools.items()},
            "dense_only_candidates": len(pools["dense"] - pools["lexical"]),
            "fates": candidate_fates(trace),
            "variants": {},
        }
        report.extend([
            "<details>", "<summary>排序变化与候选诊断（不是有效证据清单）</summary>", "",
        ])
        for name, selected in variants.items():
            current = metrics(selected, case)
            added, removed = keys(selected) - baseline_keys, baseline_keys - keys(selected)
            result["variants"][name] = {
                **current,
                "added_chunks": sorted(added), "removed_chunks": sorted(removed),
                "hits": [asdict(h) for h in selected],
            }
            report.append(
                f"- {name}：定位锚点排名 {current['anchor_rank']}；"
                f"{current['sources']} 份报告；{current['unique_context_chunks']} 个上下文块；"
                f"新增 {len(added)}／移出 {len(removed)} 块。"
            )
            if name != "baseline":
                for label, changed in (("新增", added), ("移出", removed)):
                    examples = [
                        h for h in trace.fused if (h.build_id, h.chunk_id) in changed
                    ][:2]
                    for h in examples:
                        snippet = h.snippet.replace("\n", " ")
                        report.extend([
                            "", f"{name} {label}示例：{h.chunk_id}（第 {h.page} 页）",
                            "", f"> {snippet}", "",
                        ])
        report.extend(["", "向量独有候选示例（定位摘要，不代表已验证相关）：", ""])
        examples = [h for h in trace.dense if (h.build_id, h.chunk_id) not in pools["lexical"]][:2]
        for hit in examples:
            snippet = hit.snippet.replace("\n", " ")
            report.append(f"- {hit.chunk_id}（第 {hit.page} 页）：{snippet}")
        report.append("")
        report.extend(["</details>", ""])
        save(HERE / "comparisons" / (case["id"] + ".json"), result)
        rows.append(result)
    eligible = [r for r in rows if "variants" in r]
    positives = [r for r in eligible if r["kind"] == "positive"]
    summary = {
        "manifest_sha256": manifest_hash,
        "cases": len(rows), "hybrid_cases": len(eligible),
        "excluded": [r for r in rows if "excluded" in r],
        "positive_cases": len(positives),
        "measurement_boundary": "selection before table-header enrichment",
        "capture": {
            "profile": sorted({c["profile"] for c in captures}),
            "publication_snapshots": sorted({
                c["coverage"]["publication_snapshot_ref"] for c in captures
            }),
            "median_query_ms": statistics.median(c["elapsed_ms"] for c in captures),
            "max_query_ms": max(c["elapsed_ms"] for c in captures),
            "reported_query_tokens": sum(
                c["coverage"]["retrieval"].get("query_usage", {}).get("total_tokens", 0)
                for c in captures
            ),
            "fallbacks": [
                {"case": c["case"], "reason": c["coverage"]["retrieval"].get("reason"),
                 "elapsed_ms": c["elapsed_ms"]}
                for c in captures if c["trace"]["status"] != "hybrid"
            ],
            "new_document_embedding_requests": 0,
            "automatic_query_retries": 0,
        },
        "positive_candidate_hits": {
            name: sum(r["candidate_gold"][name] for r in positives)
            for name in ("lexical", "dense", "fused")
        },
        "variants": {},
        "baseline_omission_counts": dict(Counter(
            fate["omission_stage"]
            for r in eligible for fate in r["fates"] if fate["omission_stage"]
        )),
    }
    for name in ("baseline", "source_first", "global_rrf_cap3"):
        ranks = [r["variants"][name]["anchor_rank"] for r in positives]
        summary["variants"][name] = {
            "positive_hits": sum(rank is not None for rank in ranks),
            "positive_top1": sum(rank == 1 for rank in ranks),
            "mrr": sum(1 / rank if rank else 0 for rank in ranks) / max(1, len(ranks)),
            "mean_sources": statistics.mean(r["variants"][name]["sources"] for r in eligible),
            "mean_context_chunks": statistics.mean(
                r["variants"][name]["unique_context_chunks"] for r in eligible
            ),
            "mean_repeated_chunks": statistics.mean(
                r["variants"][name]["repeated_context_chunks"] for r in eligible
            ),
            "rank_changes": [
                {"case": r["case"],
                 "before": r["variants"]["baseline"]["anchor_rank"],
                 "after": r["variants"][name]["anchor_rank"]}
                for r in positives
                if r["variants"]["baseline"]["anchor_rank"] != r["variants"][name]["anchor_rank"]
            ],
        }
    save(HERE / "summary.json", summary)
    (HERE / "evidence-report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
