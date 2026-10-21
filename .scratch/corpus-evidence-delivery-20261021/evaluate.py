"""Replay the frozen 32-query output through real tool formatting, without retrieval."""

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREVIOUS = ROOT / ".scratch/corpus-selection-audit-20261021"
MANIFEST = ROOT / ".scratch/corpus-vector-acceptance-20261020/manifest.json"
sys.path.insert(0, str(ROOT))

from plugins.corpus.preparation.read_pg import ChunkEvidence, UnitEvidence
from plugins.corpus.retrieval.delivery import delivery_views
from plugins.corpus.service import SearchHit


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def compact(text):
    return "".join(text.casefold().split())


def originals(data):
    return [
        ChunkEvidence(**{**row, "units": tuple(UnitEvidence(**unit) for unit in row["units"])})
        for row in data["chunks"].values()
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-terms", action="store_true")
    parser.add_argument("--verify-live-reads", action="store_true")
    args = parser.parse_args()
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    if args.prepare_terms:
        from dotenv import load_dotenv
        from plugins.corpus.preparation.search_pg import query_lexemes
        from plugins.corpus.preparation.negative_query import abstain_content_lexemes
        from plugins.corpus.retrieval.cli import pilot_dsn
        from plugins.corpus.retrieval.embedding import VectorConfig
        load_dotenv(ROOT / ".env")
        config = VectorConfig.from_env()
        target = pilot_dsn(config)
        save(HERE / "query-terms.json", {
            "manifest_sha256": manifest_hash,
            "terms": {
                c["id"]: abstain_content_lexemes(
                    query_lexemes(target, c["question"], sandbox_db=config.target_db)
                ) for c in cases
            },
        })
    token_file = json.loads((HERE / "query-terms.json").read_text(encoding="utf-8"))
    assert token_file["manifest_sha256"] == manifest_hash
    review = json.loads((HERE / "review.json").read_text(encoding="utf-8"))
    review_hash = hashlib.sha256((HERE / "review.json").read_bytes()).hexdigest()
    module = importlib.import_module("plugins.tools.corpus_search")
    live_service = None
    live_rows = []
    if args.verify_live_reads:
        from dotenv import load_dotenv
        from plugins.corpus.retrieval.cli import pilot_dsn
        from plugins.corpus.retrieval.embedding import VectorConfig
        from plugins.corpus.service import CorpusService
        load_dotenv(ROOT / ".env")
        live_service = CorpusService(pilot_dsn(VectorConfig.from_env()))
    report = [
        "# 证据可用性与完整句段预览试验", "",
        "不改变题目、候选和排序。人工判断栏实际由 agent 阅读全部 32 个首位锚点后填写，"
        "未经用户复核；其余 288 个锚点未做逐条相关性标注。",
        "direct 表示可回答或纠正问题前提，partial 表示只能部分回答，background 为背景，"
        "irrelevant 为无关；不判定来源观点真伪。",
        "句段由问题词元自动选择；标注和 markers 不传入预览算法。标记覆盖只是诊断代理。",
        "预览仍不等于引用取证；核心锚点可能遗漏相邻片段中的其他回答部分。", "",
    ]
    rows = []
    for case in cases:
        cid = case["id"]
        capture_path = PREVIOUS / f"captures/{cid}.json"
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        raw_path = PREVIOUS / f"returned-text/{cid}.json"
        raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
        assert capture["manifest_sha256"] == raw_data["manifest_sha256"] == manifest_hash
        hits = [SearchHit(**row) for row in capture["public_hits"]]
        evidence = originals(raw_data)
        views = delivery_views(hits, evidence, token_file["terms"][cid])
        if live_service is not None:
            started = time.monotonic()
            live_views = live_service.evidence_previews(case["question"], hits)
            assert live_views == views, (cid, "live authority differs from frozen originals")
            live_rows.append({"case": cid, "ms": (time.monotonic() - started) * 1000})

        class ReplayService:
            def search_with_coverage(self, query, limit):
                assert query == case["question"]
                return hits, capture["coverage"]

            def evidence_previews(self, query, selected):
                assert selected == hits
                return views

        with patch.object(module, "get_service", lambda: ReplayService()):
            bodies = {}
            for mode in ("off", "pilot"):
                with patch.dict(os.environ, {"CORPUS_EVIDENCE_PREVIEW": mode}):
                    bodies[mode] = asyncio.run(
                        module.corpus_search.ainvoke({"query": case["question"], "limit": 10})
                    )
        baseline, trial = (json.loads(bodies[mode]) for mode in ("off", "pilot"))
        assert trial["delivery_preview"] == "pilot"
        for left, right in zip(baseline["hits"], trial["hits"], strict=True):
            for key in ("doc_id", "locator", "context_locators", "fetch_plan"):
                assert left[key] == right[key], (cid, key)
        top_original = raw_data["chunks"][hits[0].chunk_id]["text"]
        label = review["labels"][cid]
        missing = [m for m in label["markers"] if compact(m) not in compact(top_original)]
        assert not missing, (cid, "review marker absent from original", missing)
        preview = views[0]["preview"]["text"]
        marker_coverage = {
            name: [m for m in label["markers"] if compact(m) in compact(text)]
            for name, text in (("old_snippet", hits[0].snippet), ("new_preview", preview))
        }
        core = {
            (v["core_fetch_plan"]["doc_id"], loc)
            for v in views for loc in v["core_fetch_plan"]["locators"]
        }
        full = {(h.doc_id, loc) for h in hits for loc in h.context_locators}
        assert core <= full
        budget_rows = {}
        for budget in (6000, 12000):
            modes = {}
            for mode, body in bodies.items():
                fitted = module.fit_search_payload(body, budget) if len(body) > budget else body
                payload = json.loads(fitted) if fitted else {"hits": []}
                modes[mode] = {
                    "chars": len(fitted or ""),
                    "hits": len(payload.get("hits", [])),
                    "previews": sum(
                        bool(h.get("preview", {}).get("text")) for h in payload.get("hits", [])
                    ),
                    "previews_elided": payload.get("previews_elided", False),
                    "top1_markers_visible": (
                        bool(label["markers"])
                        and bool(payload.get("hits"))
                        and all(
                            compact(m) in compact(
                                payload["hits"][0].get("preview", {}).get("text", "")
                                if mode == "pilot"
                                else payload["hits"][0].get("snippet", "")
                            ) for m in label["markers"]
                        )
                    ),
                    "labelled_chunk_in_returned_scope": any(
                        h.get("build_id") == case.get("build_id")
                        and any("chunk:" + c in h.get("context_locators", [])
                                for c in case.get("gold_chunks", []))
                        for h in payload.get("hits", [])
                    ),
                }
            budget_rows[str(budget)] = modes
        row = {
            "case": cid, "kind": case["kind"], "review": label,
            "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            "original_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "original_retrieval": capture["coverage"]["retrieval"]["used"],
            "top_chunk": hits[0].chunk_id,
            "top_original_chars": len(top_original),
            "old_snippet": hits[0].snippet,
            "preview": views[0]["preview"],
            "marker_coverage": marker_coverage,
            "core_chunks": len(core), "full_chunks": len(full),
            "original_context_occurrences": sum(len(h.context_locators) for h in hits),
            "preview_statuses": dict(Counter(v["preview"]["status"] for v in views)),
            "preview_chars": [len(v["preview"]["text"]) for v in views],
            "body_chars": {mode: len(body) for mode, body in bodies.items()},
            "budget": budget_rows,
        }
        save(HERE / f"cases/{cid}.json", row)
        save(HERE / f"payloads/{cid}.json", trial)
        rows.append(row)
        report.extend([
            f"## {cid}：{case['question']}", "",
            f"首位原文判断：**{label['class']}**。{label['reason']}",
            f"原运行通道：{row['original_retrieval']}；锚点：{hits[0].chunk_id}", "",
            "旧定位摘要：", "", "> " + hits[0].snippet.replace("\n", "\n> "), "",
            "新的完整句段预览（非自动判断为答案）：", "",
            "> " + (preview or f"未生成：{views[0]['preview']['status']}").replace("\n", "\n> "), "",
            f"支持要点标记：{label['markers']}；预览保留：{marker_coverage['new_preview']}",
            f"全部返回命中的首读范围：{len(core)} 块；原完整范围：{len(full)} 块。",
            f"[实际原文](../corpus-selection-audit-20261021/returned-text/{cid}.md)", "",
        ])
    direct = [r for r in rows if r["review"]["class"] == "direct"]
    summary = {
        "manifest_sha256": manifest_hash, "review_sha256": review_hash,
        "review_scope": review["scope"],
        "cases": len(rows),
        "top1_classes": dict(Counter(r["review"]["class"] for r in rows)),
        "positive_top1_classes": dict(Counter(
            r["review"]["class"] for r in rows if r["kind"] == "positive"
        )),
        "direct_count": len(direct),
        "all_markers_visible": {
            name: sum(
                len(r["marker_coverage"][name]) == len(r["review"]["markers"]) for r in direct
            ) for name in ("old_snippet", "new_preview")
        },
        "mean_old_snippet_chars": statistics.mean(
            len(re.sub(r"<[^>]+>", "", h["snippet"]))
            for case in cases
            for h in json.loads((PREVIOUS / f"captures/{case['id']}.json").read_text())["public_hits"]
        ),
        "mean_preview_chars_all_hits": statistics.mean(c for r in rows for c in r["preview_chars"]),
        "mean_core_chunks": statistics.mean(r["core_chunks"] for r in rows),
        "mean_full_chunks": statistics.mean(r["full_chunks"] for r in rows),
        "mean_context_occurrences": statistics.mean(r["original_context_occurrences"] for r in rows),
        "preview_statuses": dict(sum((Counter(r["preview_statuses"]) for r in rows), Counter())),
        "budget": {
            str(b): {
                mode: {
                    "mean_hits": statistics.mean(r["budget"][str(b)][mode]["hits"] for r in rows),
                    "total_previews": sum(r["budget"][str(b)][mode]["previews"] for r in rows),
                    "direct_top1_all_markers": sum(
                        r["budget"][str(b)][mode]["top1_markers_visible"] for r in direct
                    ),
                    "positive_labelled_chunk_coverage": sum(
                        r["budget"][str(b)][mode]["labelled_chunk_in_returned_scope"]
                        for r in rows if r["kind"] == "positive"
                    ),
                } for mode in ("off", "pilot")
            } for b in (6000, 12000)
        },
        "new_searches": 0, "new_embeddings": 0,
        "limitations": [
            "Core-only reading can miss adjacent answer parts (p16); expansion is not removed.",
            "No autonomous main-agent run; fewer chunks is not measured fewer calls or lower cost.",
            "Top-1 review does not measure precision across all hits.",
        ],
    }
    save(HERE / "summary.json", summary)
    if live_rows:
        save(HERE / "live-read-verification.json", {
            "cases": live_rows,
            "all_views_equal": True,
            "median_ms": statistics.median(r["ms"] for r in live_rows),
            "max_ms": max(r["ms"] for r in live_rows),
        })
    (HERE / "evidence-review.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
