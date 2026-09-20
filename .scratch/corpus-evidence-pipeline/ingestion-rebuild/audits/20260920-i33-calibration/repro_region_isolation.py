"""Read-only FIX-3 / region-isolation preflight (Stage-1). Never writes PG.

Measures quote contiguity (34 targets) under several line-level reading-order
strategies so we can decide whether any reader/region change is worth a full
re-ingestion. Strategies: before (single-col y-sort), center-cluster (guide
FIX-1), x0-cluster (right-sidebar boxes share a distinct left edge), and
region bands (header/footer/legend short blocks isolated, ordering header ->
body -> footer).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import pymupdf

from plugins.corpus.preparation.readers.pdf_reader import _merge_lines, _page_lines

WS = re.compile(r"\s+")
def norm(s: object) -> str:
    return WS.sub("", s) if isinstance(s, str) else ""

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


def cols_of(normal, content_w, key):
    if not normal:
        return []
    order = sorted(normal, key=key)
    th = content_w * 0.18
    cols = [[order[0]]]
    cur = key(order[0])
    for ln in order[1:]:
        v = key(ln)
        if v - cur >= th:
            cols.append([])
        cols[-1].append(ln)
        cur = v
    return cols


_cache = {}


def page_stream(source_id: str, page_no: int, mode: str) -> str:
    key = (source_id, page_no, mode)
    if key in _cache:
        return _cache[key]
    doc = pymupdf.open(SRC[source_id])
    try:
        lines = _page_lines(doc[page_no - 1])
    finally:
        doc.close()
    if not lines:
        _cache[key] = ""
        return ""
    cw = max(l.bbox[2] for l in lines) - min(l.bbox[0] for l in lines)
    center = lambda l: (l.bbox[0] + l.bbox[2]) / 2  # noqa: E731
    x0k = lambda l: l.bbox[0]  # noqa: E731
    spanners = [l for l in lines if (l.bbox[2] - l.bbox[0]) >= cw * 0.6]
    normal = [l for l in lines if (l.bbox[2] - l.bbox[0]) < cw * 0.6]

    def assemble(cols, spanners, emit_spanners="end"):
        for c in cols:
            c.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
        parts: list[str] = []
        for c in cols:
            parts.extend("\n".join(l.text for l in p) for p in _merge_lines(c))
        spanners.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
        sp = [l.text for l in spanners]
        if emit_spanners == "start":
            return "\n".join(sp + parts)
        return "\n".join(parts + sp)

    text = ""
    if mode == "before":
        ordered = sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0]))
        text = "\n".join("\n".join(l.text for l in p) for p in _merge_lines(ordered))
    elif mode == "center":
        text = assemble(cols_of(normal, cw, center), spanners)
    elif mode == "x0":
        text = assemble(cols_of(normal, cw, x0k), spanners)
    elif mode == "x0hdr":
        # FIX-3-ish: header/footer separated by y-band, sidebar by x0-cluster.
        ymin = min(normal, key=lambda l: l.bbox[1]).bbox[1]
        ymax = max(normal, key=lambda l: l.bbox[3]).bbox[3]
        span = ymax - ymin
        head = [l for l in normal if l.bbox[3] < ymin + span * 0.12]
        foot = [l for l in normal if l.bbox[1] > ymin + span * 0.88]
        body = [l for l in normal if l not in head and l not in foot]
        head.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
        foot.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
        body_str = assemble(cols_of(body, cw, x0k), spanners)
        head_str = "\n".join(t.text for t in head)
        foot_str = "\n".join(t.text for t in foot)
        text = "\n".join(x for x in (head_str, body_str, foot_str) if x)
    _cache[key] = text
    return text


def main() -> None:
    diag = json.loads((HERE / "evidence-diagnosis.json").read_text())
    gold = {json.loads(l)["query_id"]: json.loads(l)
            for l in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]
    modes = ["before", "center", "x0", "x0hdr"]
    counts = {m: Counter() for m in modes}
    per = {m: [] for m in modes}
    for r in rows:
        src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
        qn = norm(next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                       if et["target_id"] == r["target_id"]))
        for m in modes:
            hit = qn in norm(page_stream(src, pg, m))
            counts[m]["miss" if not hit else "hit"] += 1
            per[m].append(0 if hit else 1)
    out = {m: {"hit": counts[m]["hit"], "miss": counts[m]["miss"]} for m in modes}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    (HERE / "remediation-region-repro.json").write_text(
        json.dumps({"summary": out, "per_mode_miss": {m: per[m] for m in modes}},
                   ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()