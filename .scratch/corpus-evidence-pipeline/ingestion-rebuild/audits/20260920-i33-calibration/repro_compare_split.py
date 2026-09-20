"""Compare real reader emission with split_columns disabled (pure native order)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
root = HERE.parents[2]
sys.path.insert(0, str(root))

import plugins.corpus.preparation.readers.pdf_reader as P  # noqa: E402
from plugins.corpus.preparation.contract import UnitStatus  # noqa: E402

WS = re.compile(r"\s+")


def norm(s):  # noqa: ANN001, ANN201
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


def build(disable_split: bool) -> dict:
    orig = P._split_columns
    if disable_split:
        P._split_columns = lambda lines, pw: None
    try:
        from plugins.corpus.preparation.readers import read_document
        diag = json.loads((HERE / "evidence-diagnosis.json").read_text())
        gold = {json.loads(l)["query_id"]: json.loads(l)
                for l in (HERE.parents[1] / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
        rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]
        cache: dict = {}
        hit = miss = 0
        missed = []
        for r in rows:
            src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
            q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                     if et["target_id"] == r["target_id"])
            qn = norm(q)
            if src not in cache:
                res = read_document(SRC[src])
                pages: dict[int, list] = {}
                for u in res.units:
                    if u.status is UnitStatus.KEPT:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                cache[src] = {pg_: "\n".join(x) for pg_, x in pages.items()}
            if qn in norm(cache[src].get(pg, "")):
                hit += 1
            else:
                miss += 1
                missed.append(f"{r['query_id']} {r['target_id']} p{pg}")
        return {"hit": hit, "miss": miss, "missed": missed}
    finally:
        if disable_split:
            P._split_columns = orig


if __name__ == "__main__":
    with_split = build(False)
    no_split = build(True)
    print("with split_columns :", json.dumps({k: v for k, v in with_split.items() if k != "missed"}))
    print("without            :", json.dumps({k: v for k, v in no_split.items() if k != "missed"}))
    import os
    os.chdir(HERE)
    (HERE / "remediation-compare-split.json").write_text(json.dumps(
        {"with_split": with_split, "without_split": no_split}, ensure_ascii=False, indent=2) + "\n")