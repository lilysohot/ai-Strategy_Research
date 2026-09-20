"""只读复算：reader-pdf-4（保留原生序 + 分栏「只标记不重排」）在 6 份 dev PDF 上的 34 条命中。

对照基线来自 I3-3（audits/20260920-i33-calibration）：
- before（reader-pdf-2，全局 (y,x) 重排）12 / 22
- reader-pdf-3（保留原生序，仍强制左→右重排）23 / 11
- 本轮 reader-pdf-4 目标 28 / 6，且不得出现「绿→红」回退。

不写 PG、不改金标、不覆盖 I3-3 任何已冻结产物（输出到本目录新文件）。
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

from plugins.corpus.preparation.contract import UnitStatus  # noqa: E402
from plugins.corpus.preparation.readers import read_document  # noqa: E402

WS = re.compile(r"\s+")

MAOTAI = "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11"

SRC = {
    MAOTAI:
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


def norm(s: object) -> str:
    return WS.sub("", s) if isinstance(s, str) else ""


def kept_pages(path: str) -> dict[int, str]:
    result = read_document(path)
    assert result.extractor_rev.startswith("reader-pdf-5+"), result.extractor_rev
    pages: dict[int, list[str]] = {}
    for u in result.units:
        if u.status is not UnitStatus.KEPT:
            continue
        pages.setdefault(u.location.page, []).append(u.raw_text)
    return {pg: "\n".join(lines) for pg, lines in pages.items()}


def main() -> None:
    diag = json.loads((I33 / "evidence-diagnosis.json").read_text())
    gold = {json.loads(line)["query_id"]: json.loads(line)
            for line in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]
    cache: dict[str, dict[int, str]] = {}
    hit = miss = 0
    missed: list[str] = []
    for r in rows:
        src, pg = r["source_id"], int(r["required_locator"][0].split(":")[1])
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        if src not in cache:
            cache[src] = kept_pages(SRC[src])
        if norm(q) in norm(cache[src].get(pg, "")):
            hit += 1
        else:
            miss += 1
            missed.append(f"{r['query_id']} {r['target_id']} p{pg}")

    base = json.loads((I33 / "remediation-reader-native-verify.json").read_text())
    base_missed = set(base["missed"])
    now_missed = set(missed)
    out = {
        "hit": hit,
        "miss": miss,
        "missed": missed,
        "recovered_vs_reader_pdf_3": sorted(base_missed - now_missed),
        "regressed_vs_reader_pdf_3": sorted(now_missed - base_missed),
        "company001_p1_contiguous": norm("我们维持26-28年EPS预测值67.74/70.77/73.84元")
        in norm(cache.get(MAOTAI, {}).get(1, "")),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    (HERE / "native-order-verify.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
