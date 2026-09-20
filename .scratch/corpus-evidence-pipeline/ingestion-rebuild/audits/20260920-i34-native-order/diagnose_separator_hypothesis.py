"""只读诊断：6 条剩余的失败，是「分隔符」还是「顺序/丢格」造成的（普遍检验，不针对特定文档）。

对 34 条逐条检验三个通用变体：
  v0 = reader-pdf-4 kept 文本（去空白）
  v1 = kept 文本去掉单元格分隔符 "|" 后再去空白
  v2 = pymupdf 原生阅读序 get_text("text")（去空白）
另外打印剩余 6 条在原生序中的上下文，用于确认「引文顺序是否等于原文原生序」。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
I33 = HERE.parent / "20260920-i33-calibration"
BASE = HERE.parents[1]
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


def main() -> None:
    diag = json.loads((I33 / "evidence-diagnosis.json").read_text())
    gold = {json.loads(line)["query_id"]: json.loads(line)
            for line in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]

    kept_cache: dict[str, dict[int, str]] = {}
    native_cache: dict[tuple[str, int], str] = {}
    v0 = v1 = v2 = 0
    remain: list[str] = []
    for r in rows:
        src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        qn = norm(q)
        if src not in kept_cache:
            kept_cache[src] = V.kept_pages(V.SRC[src])
        if (src, pg) not in native_cache:
            doc = pymupdf.open(V.SRC[src])
            native_cache[(src, pg)] = doc[pg - 1].get_text("text")
            doc.close()
        kept = kept_cache[src].get(pg, "")
        h0 = qn in norm(kept)
        h1 = qn in norm(kept.replace("|", ""))
        h2 = qn in norm(native_cache[(src, pg)])
        v0 += h0
        v1 += h1
        v2 += h2
        if not h0:
            remain.append(f"{r['query_id']} {r['target_id']} p{pg}  "
                          f"v1(去|)={'HIT' if h1 else 'miss'}  v2(原生序)={'HIT' if h2 else 'miss'}")

    print(f"v0 kept(reader-pdf-5)          : {v0}/34")
    print(f"v1 kept 去掉 '|' 分隔符         : {v1}/34")
    print(f"v2 pymupdf 原生阅读序           : {v2}/34")
    print("---- 剩余 6 条在三种变体下的表现 ----")
    print("\n".join(remain))

    print("---- 剩余条目的原生序上下文（确认引文顺序是否为原文原生序）----")
    for r in rows:
        src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        qn = norm(q)
        if qn in norm(kept_cache[src].get(pg, "")):
            continue
        txt = norm(native_cache[(src, pg)])
        pos = txt.find(qn)
        print("=" * 84)
        print(f"ITEM {r['query_id']} {r['target_id']} p{pg}  原生序位置={pos}  引文长度(去空白)={len(qn)}")
        print("原生序前后文:", txt[max(0, pos - 60): pos + len(qn) + 60])


if __name__ == "__main__":
    main()
