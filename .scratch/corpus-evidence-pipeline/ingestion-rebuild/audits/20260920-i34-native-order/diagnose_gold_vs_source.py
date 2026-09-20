"""只读诊断：34 条引文失败是「我们代码的错」还是「引文顺序非原文阅读序」。

普遍判据（不针对任何特定文档/页面）：
  A. 引文在 pymupdf 原生阅读序文本中连续：
       A1. 在我们 reader 的 kept 拼接文本中也连续 -> 不该失败（异常）
       A2. 在 kept 中不连续 -> **我们代码的错**（reader 发射/拼接改变了原生序）
  B. 引文在 pymupdf 原生阅读序中不连续：
       -> 引文顺序不是原文阅读序（跨结构拼接/金标侧采样），**代码修不了**
       B1. 但若在「旧版 (y,x) 全局排序」的拼接文本中连续 -> **金标引文是旧代码 bug 的化石**

原生序取两个独立来源：page.get_text("text")（pymupdf 阅读序）与块序拼接。
不写 PG、不改金标、不覆盖任何既有产物。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
I33 = HERE.parent / "20260920-i33-calibration"
BASE = HERE.parents[1]  # ingestion-rebuild
ROOT = HERE
while not (ROOT / "plugins").is_dir():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import pymupdf  # noqa: E402
import verify_native_order as V  # noqa: E402

WS = re.compile(r"\s+")


def norm(s: object) -> str:
    return WS.sub("", s) if isinstance(s, str) else ""


def native_texts(page: pymupdf.Page) -> tuple[str, str]:
    """(pymupdf 阅读序文本, 旧版 (y,x) 全局排序文本)"""
    reading = page.get_text("text")
    lines: list[tuple[float, float, str]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"])
            x0, y0, _x1, _y1 = line["bbox"]
            lines.append((y0, x0, text))
    lines.sort(key=lambda item: (item[0], item[1]))  # 旧版全局 (y,x) 重排
    legacy = "\n".join(item[2] for item in lines)
    return reading, legacy


def main() -> None:
    diag = json.loads((I33 / "evidence-diagnosis.json").read_text())
    gold = {json.loads(line)["query_id"]: json.loads(line)
            for line in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]

    kept_cache: dict[str, dict[int, str]] = {}
    page_cache: dict[tuple[str, int], tuple[str, str]] = {}
    out: list[dict[str, object]] = []
    for r in rows:
        src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        qn = norm(q)
        if src not in kept_cache:
            kept_cache[src] = V.kept_pages(V.SRC[src])
        if (src, pg) not in page_cache:
            doc = pymupdf.open(V.SRC[src])
            page_cache[(src, pg)] = native_texts(doc[pg - 1])
            doc.close()
        kept = norm(kept_cache[src].get(pg, ""))
        reading, legacy = page_cache[(src, pg)]
        n_reading, n_legacy = norm(reading), norm(legacy)
        out.append({
            "item": f"{r['query_id']} {r['target_id']} p{pg}",
            "in_kept_reader_pdf_4": qn in kept,
            "in_native_reading_order": qn in n_reading,
            "in_native_legacy_yx": qn in n_legacy,
        })

    cat_a2 = [o["item"] for o in out if o["in_native_reading_order"] and not o["in_kept_reader_pdf_4"]]
    cat_a1 = [o["item"] for o in out if o["in_native_reading_order"] and o["in_kept_reader_pdf_4"]]
    cat_b1 = [o["item"] for o in out
              if not o["in_native_reading_order"] and o["in_native_legacy_yx"]]
    cat_b = [o["item"] for o in out
             if not o["in_native_reading_order"] and not o["in_native_legacy_yx"]]

    print(f"TOTAL {len(out)}")
    print(f"A1 原生序与 kept 均连续（异常，不该失败） : {len(cat_a1)} {cat_a1}")
    print(f"A2 原生序连续、kept 不连续 => 我们代码的错   : {len(cat_a2)} {cat_a2}")
    print(f"B1 原生序不连续、旧版(y,x)才连续 => 引文化石 : {len(cat_b1)} {cat_b1}")
    print(f"B  两者都不连续 => 引文顺序非原文阅读序     : {len(cat_b)} {cat_b}")
    print("---- 逐条 ----")
    for o in out:
        flags = ("K" if o["in_kept_reader_pdf_4"] else "-") + \
                ("N" if o["in_native_reading_order"] else "-") + \
                ("L" if o["in_native_legacy_yx"] else "-")
        print(f"  {flags}  {o['item']}")
    print("(K=kept(reader-pdf-4) 命中, N=pymupdf 原生阅读序命中, L=旧版(y,x)序命中)")
    (HERE / "gold-vs-source.json").write_text(
        json.dumps({"targets": out, "A2_code_error": cat_a2,
                    "B1_gold_fossil": cat_b1, "B_unreachable": cat_b},
                   ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
