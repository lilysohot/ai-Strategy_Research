"""Read-only deep re-alignment probe (Stage-1 part 3): coordinate/reading-order.

Never writes PG. Measures quote contiguity (34 targets) under richer full-page
reading-order reconstructions than the earlier line-level strategies, so we can
tell whether ANY ingestion-side fix can break the hit17 ceiling. Also emits a
per-target 3-way triage (A/B/C) so unrecoverable targets are enumerated.
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


def cols_of(lines, key, gap):
    if not lines:
        return []
    order = sorted(lines, key=key)
    cols = [[order[0]]]
    cur = key(order[0])
    for ln in order[1:]:
        v = key(ln)
        if v - cur >= gap:
            cols.append([])
        cols[-1].append(ln)
        cur = v
    return cols


_cache: dict = {}


def _read_lines(src, page_no: int) -> list:
    with pymupdf.open(SRC[src]) as doc:
        payload = doc[page_no - 1].get_text("dict")
    per_block: list[list] = []
    for b in payload.get("blocks", []):
        if b.get("type") != 0:
            continue
        blk_lines = [
            l for l in b.get("lines", []) if any(str(s.get("text", "")).strip() for s in l.get("spans", []))
        ]
        if blk_lines:
            per_block.append(blk_lines)
    return per_block


def page_size(src) -> tuple[float, float]:
    with pymupdf.open(SRC[src]) as doc:
        r = doc[0].rect
        return r.width, r.height


def page_stream_blocks(src: str, page_no: int, mode: str) -> str:
    key = (src, page_no, mode)
    if key in _cache:
        return _cache[key]
    blocks = _read_lines(src, page_no)
    if not blocks:
        _cache[key] = ""
        return ""

    with pymupdf.open(SRC[src]) as doc:
        lines = _page_lines(doc[page_no - 1])
    if not lines:
        _cache[key] = ""
        return ""

    cwmax = max(l.bbox[2] for l in lines)
    xmin = min(l.bbox[0] for l in lines)
    content_w = cwmax - xmin
    spanner_w = content_w * 0.6
    spanners = [l for l in lines if (l.bbox[2] - l.bbox[0]) >= spanner_w]
    normal = [l for l in lines if (l.bbox[2] - l.bbox[0]) < spanner_w]

    x0k = lambda l: l.bbox[0]  # noqa: E731
    center = lambda l: (l.bbox[0] + l.bbox[2]) / 2  # noqa: E731

    def assemble(cols, sorter, sp_at="end"):
        for c in cols:
            c.sort(key=sorter)
        parts = []
        for c in cols:
            for p in _merge_lines(c):
                parts.append("\n".join(l.text for l in p))
        spanners.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
        sp = [l.text for l in spanners]
        if sp_at == "start":
            return "\n".join(sp + parts)
        return "\n".join(parts + sp)

    col_sorter = lambda l: (l.bbox[1], l.bbox[0])  # noqa: E731

    text = ""
    if mode == "before":
        ordered = sorted(lines, key=col_sorter)
        text = "\n".join("\n".join(l.text for l in p) for p in _merge_lines(ordered))
    elif mode == "center":
        text = assemble(cols_of(normal, center, content_w * 0.18), col_sorter)
    elif mode == "x0":
        text = assemble(cols_of(normal, x0k, content_w * 0.18), col_sorter)
    elif mode == "x0sp_last":
        # right column (sidebar) isolated by x0 cluster, emitted LAST regardless
        cols = cols_of(normal, x0k, content_w * 0.18)
        if len(cols) >= 2:
            body = cols[:-1]
            side = cols[-1]
            body.sort(key=lambda c: min(l.bbox[0] for l in c))
            side.sort(key=lambda l: l.bbox[0])
            parts = []
            for c in body + [side]:
                c.sort(key=col_sorter)
                for p in _merge_lines(c):
                    parts.append("\n".join(l.text for l in p))
            spanners.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
            text = "\n".join(parts + [l.text for l in spanners])
        else:
            text = assemble(cols, col_sorter)
    elif mode == "x0hdr":
        ymin = min(normal, key=lambda l: l.bbox[1]).bbox[1]
        ymax = max(normal, key=lambda l: l.bbox[3]).bbox[3]
        span = ymax - ymin
        head = [l for l in normal if l.bbox[3] < ymin + span * 0.12]
        foot = [l for l in normal if l.bbox[1] > ymin + span * 0.88]
        body = [l for l in normal if l not in head and l not in foot]
        head.sort(key=col_sorter)
        foot.sort(key=col_sorter)
        body_str = assemble(cols_of(body, x0k, content_w * 0.18), col_sorter)
        head_str = "\n".join(t.text for t in head)
        foot_str = "\n".join(t.text for t in foot)
        text = "\n".join(x for x in (head_str, body_str, foot_str) if x)
    elif mode == "blockcols":
        # respect pymupdf block boundaries; order blocks by (top, x0-majority)
        ordered_blocks = []
        for blk in blocks:
            ls = [_page_line_view(l) for l in blk]
            if not ls:
                continue
            top = min(l.bbox[1] for l in ls)
            bx0 = min(l.bbox[0] for l in ls)
            ordered_blocks.append((top, bx0, ls))
        ordered_blocks.sort(key=lambda t: (t[0], t[1]))
        text = "\n".join(
            "\n".join(l.text for l in blk) for _, _, blk in ordered_blocks
        )
    elif mode == "blockraw":
        # pymupdf NATIVE block order (content stream order), untouched; lines in block order
        text = "\n".join(
            "\n".join(str(s.get("text", "")) for l in blk
                      for s in l.get("spans", []))
            for blk in blocks
        )
    elif mode == "blockheadfoot":
        # blockcols + header/footer region isolation (FIX-3): top-strip blocks first,
        # bottom-strip blocks last, middle blocks by (top, x0).
        vls = [_page_line_view(l) for l in [z for blk in blocks for z in blk]]
        ymin = min(l.bbox[1] for l in vls)
        ymax = max(l.bbox[3] for l in vls)
        span = ymax - ymin
        head_buf, mid_buf, foot_buf = [], [], []
        for blk in blocks:
            ls = [_page_line_view(l) for l in blk]
            if not ls:
                continue
            top = min(l.bbox[1] for l in ls)
            bot = max(l.bbox[3] for l in ls)
            ent = (top, min(l.bbox[0] for l in ls), ls)
            if bot < ymin + span * 0.15:
                head_buf.append(ent)
            elif top > ymin + span * 0.85:
                foot_buf.append(ent)
            else:
                mid_buf.append(ent)
        out = []
        for buf in (sorted(head_buf), sorted(mid_buf), sorted(foot_buf)):
            for _, _, ls in buf:
                out.append("\n".join(l.text for l in ls))
        text = "\n".join(out)
    elif mode == "pytext":
        with pymupdf.open(SRC[src]) as doc:
            text = doc[page_no - 1].get_text("text")
    _cache[key] = text
    return text


def _block_lines(blk):
    return [_page_line_view(l) for l in blk]


def _page_line_view(raw):
    b0s, b1s, b2s, b3s = zip(*[tuple(s["bbox"]) for s in raw.get("spans", [])])
    bbox = (min(b0s), min(b1s), max(b2s), max(b3s))
    size = max(float(s.get("size", 0.0)) for s in raw.get("spans", []))
    text = "".join(str(s["text"]) for s in raw.get("spans", []))
    L = type("_V", (), {})
    inst = L()
    inst.bbox = bbox
    inst.text = text
    inst.size = size
    return inst


def main() -> None:
    diag = json.loads((HERE / "evidence-diagnosis.json").read_text())
    gold = {json.loads(l)["query_id"]: json.loads(l)
            for l in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]
    modes = ["before", "center", "x0", "blockraw", "blockcols", "pytext"]
    counts = {m: Counter() for m in modes}
    per = {m: [] for m in modes}
    detail: list[dict] = []
    for r in rows:
        src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        qn = norm(q)
        row = {"query_id": r["query_id"], "target_id": r["target_id"], "page": pg}
        for m in modes:
            hit = qn in norm(page_stream_blocks(src, pg, m))
            counts[m]["hit" if hit else "miss"] += 1
            per[m].append(0 if hit else 1)
            row[m] = "hit" if hit else "miss"
        detail.append(row)
    best = min(modes, key=lambda m: counts[m]["miss"])
    out = {"summary": {m: {"hit": counts[m]["hit"], "miss": counts[m]["miss"]} for m in modes},
           "best": best,
           "per_target": {m: per[m] for m in modes}}
    print(json.dumps({"summary": out["summary"], "best": best}, ensure_ascii=False, indent=2))
    print("\n-- targets still missed in best mode {} --".format(best))
    for row in sorted(detail, key=lambda d: (d["query_id"], d["target_id"])):
        if row[best] == "miss":
            print(row["query_id"], row["target_id"], "p{}".format(row["page"]))
    (HERE / "remediation-coord-deep.json").write_text(
        json.dumps({"out": out, "detail": detail}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()