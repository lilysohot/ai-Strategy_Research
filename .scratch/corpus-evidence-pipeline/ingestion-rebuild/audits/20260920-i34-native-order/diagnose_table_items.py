"""只读诊断：6 条表格类未命中的「具体错在哪」。

对每条：打印金标引文、它在页内去空白文本中的逐子句位置、以及该页 KEPT 拼接文本，
用来展示「引文子句都在、但被表格结构化重组打散」的真实样子。
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

import verify_native_order as V  # noqa: E402

MISSED6 = {
    "industry-003 a-3 p10",
    "industry-008 a-2 p10",
    "macro-001 a-3 p3",
    "macro-002 e4 p1",
    "macro-003 a-2 p1",
    "macro-003 a-4 p1",
}


def main() -> None:
    diag = json.loads((I33 / "evidence-diagnosis.json").read_text())
    gold = {json.loads(line)["query_id"]: json.loads(line)
            for line in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]
    cache: dict[str, dict[int, str]] = {}
    for r in rows:
        pg = int(r["required_locator"][0].split(":")[1])
        key = f"{r['query_id']} {r['target_id']} p{pg}"
        if key not in MISSED6:
            continue
        src = r["source_id"]
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        if src not in cache:
            cache[src] = V.kept_pages(V.SRC[src])
        ptext = cache[src].get(pg, "")
        print("=" * 88)
        print("ITEM   ", key)
        print("LOCATOR", r["required_locator"])
        print("QUOTE  ", repr(q))
        parts = [p for p in re.split(r"[\n；;。]", q) if len(V.norm(p)) >= 2]
        ntext = V.norm(ptext)
        print("逐子句在页内去空白文本中的位置（-1=子句整体缺失）：")
        for p in parts:
            idx = ntext.find(V.norm(p))
            print(f"    {'OK' if idx >= 0 else 'MISS'}  pos={idx}  {p!r}")
        print("---- 该页 KEPT 拼接文本（前 2400 字符）----")
        print(ptext[:2400])


if __name__ == "__main__":
    main()
