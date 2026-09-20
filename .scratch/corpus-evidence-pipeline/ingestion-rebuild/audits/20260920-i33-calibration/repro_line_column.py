"""Read-only line-level FIX-1 feasibility (Stage-1 preflight). Never writes PG.

Reads the real source PDFs page-by-page and simulates the reader's paragraph
assembly under (a) current single-column (y-sort all lines) and (b) x-center
column clustering (guide FIX-1), then checks how many of the 34 quotes become
norm-contiguous. Tells us whether a reader-level change can realistically get
34 -> <=2 BEFORE we bump READER_PDF_REV and re-ingest the whole corpus.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import pymupdf

from plugins.corpus.preparation.readers.pdf_reader import _merge_lines, _page_lines

WS = re.compile(r"\s+")
def norm(s: object) -> str:
    return WS.sub("", s) if isinstance(s, str) else ""

# source_id -> pdf path (verified via sha256)
SRC = {
    "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11":
        "data/corpus/2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-贵州茅台-600519-报表实质扎实-经营底部已过-贵州茅台-600519-2026年中报点评-e034bdac.pdf",
    "dddc7cd0cb74d085d851df3772aedcf68779b61087a365d14eb53ff5bb4d7afa":
        "data/corpus/2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报点评-半导体划片机国内龙头-经营拐点向上-b6beb6ee.pdf",
    "174b64628f35aca60909d11b509bc7b7e87a9f4613a03a1da6c01d720a8cbcb0":
        "data/corpus/2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资-十问十答-7463f4d0.pdf",
    "f8e316969b7cfdcd3bfde7f25320d58e95527fbdc8304ced9ca6738980051560":
        "data/corpus/2026-09-06_2026.09.06-华福证券-华福证券-基础化工行业新材料周报-英伟达带火-新材料-电子特气涨幅超240-aa8e026a.pdf",
    "793b39673d31e8a8310e89a9171567dfb0008444b669cd6e225dc354329a880a":
        "data/corpus/2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加息的门槛-6fc25e24.pdf",
    "cc03f55bc5a24d3dcf69df6148faca84d465c18ff3f7110f5813b6300c5ea128":
        "data/corpus/2026-09-06_2026.09.06-华创证券-宏观专题-从分化到收敛-可能的路径与挑战-投石问-k-系列八-81e10069.pdf",
}

# target bounds per (source,page): remember which lines lie inside a table bbox? We skip
# exact table exclusion for feasibility (reader removes table text). Keep simple.

_stream_cache = {}


def page_streams(source_id: str, page_no: int, mode: str) -> str:
    key = (source_id, page_no, mode)
    if key in _stream_cache:
        return _stream_cache[key]
    doc = pymupdf.open(SRC[source_id])
    try:
        page = doc[page_no - 1]
        lines = _page_lines(page)
    finally:
        doc.close()
    if not lines:
        _stream_cache[key] = ""
        return ""
    content_w = max(ln.bbox[2] for ln in lines) - min(ln.bbox[0] for ln in lines)
    if mode == "before":
        ordered = sorted(lines, key=lambda ln: (ln.bbox[1], ln.bbox[0]))
        text = "\n".join(
            "\n".join(ln.text for ln in para) for para in _merge_lines(ordered)
        )
    else:  # after: x-center clustering, col-major
        spanners = [ln for ln in lines if (ln.bbox[2] - ln.bbox[0]) >= content_w * 0.6]
        normal = [ln for ln in lines if (ln.bbox[2] - ln.bbox[0]) < content_w * 0.6]
        order = sorted(normal, key=lambda ln: (ln.bbox[0] + ln.bbox[2]) / 2)
        cols: list[list] = []
        if order:
            cols = [[order[0]]]
            cur = (order[0].bbox[0] + order[0].bbox[2]) / 2
            for ln in order[1:]:
                cx = (ln.bbox[0] + ln.bbox[2]) / 2
                if cx - cur >= content_w * 0.18:
                    cols.append([])
                cols[-1].append(ln)
                cur = cx
        parts: list[str] = []
        for col in cols:
            col.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))
            parts.extend("\n".join(ln.text for ln in p) for p in _merge_lines(col))
        spanners.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))
        for sp in spanners:
            parts.append(sp.text)
        text = "\n".join(parts)
    _stream_cache[key] = text
    return text


def main() -> None:
    diag = json.loads((HERE / "evidence-diagnosis.json").read_text())
    gold = {
        json.loads(l)["query_id"]: json.loads(l)
        for l in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()
    }
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]
    stats: dict[str, Counter] = {"before": Counter(), "after": Counter()}
    details = []
    for r in rows:
        qid, tid = r["query_id"], r["target_id"]
        src = r["source_id"]
        pg = int(r["required_locator"][0].split(":")[1])
        quote = next(
            (et["quote"] for et in gold[qid].get("evidence_targets", [])
             if et["target_id"] == tid),
            None,
        )
        if quote is None:
            continue
        qn = norm(quote)
        before = qn in norm(page_streams(src, pg, "before"))
        after = qn in norm(page_streams(src, pg, "after"))
        stats["before"]["hit" if before else "miss"] += 1
        stats["after"]["hit" if after else "miss"] += 1
        details.append({"query": qid, "target": tid, "page": pg,
                        "before": before, "after": after})
    out = {"before": dict(stats["before"]), "after": dict(stats["after"]),
           "n": len(details)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    still_miss = [d for d in details if not d["after"]]
    print("still missing after clustering:", len(still_miss))
    for d in still_miss:
        print("  ", d["query"], d["target"], "p", d["page"])
    (HERE / "remediation-line-repro.json").write_text(
        json.dumps({"summary": out, "details": details}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()