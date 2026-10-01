"""只读：全 build 扫描引文所在 chunk，与 delivered 集合比对，区分检索覆盖 vs 跨块拆分。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def norm(s):
    return WS.sub("", s or "")


CASES = {
    "c1ddcd8a-realestate": ("a6be5fb919b5ca0f", "地产竣工链条：钛白粉、玻璃价格处于低位水平。 本周钛白粉、玻璃的价格环比分别-0.36%、-0.97%，平板玻璃本周开工率 67.19%。"),
    "b7e932c8-index": ("5a213a956083ee64", "本周主要宽基指数普遍下跌 ，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；成长风格方面 ，创业板指下跌 4.03%，科创50下跌5.10%"),
    "b7e932c8-industry": ("5a213a956083ee64", "行业层面 ，本周申万 31个行业中 14个录得正收益 ，机构低配板块表现居前 ，传媒、银行和农林牧渔涨幅居前 ，分别上涨 6.0%、4.0%、3.3%；电子、有色金属和建筑材料表现较弱，分别下跌5.4%、5.0%、4.3%。"),
}

d = json.loads((HERE / "e6-data-delivery-holdout-rerun.json").read_text(encoding="utf-8"))
targets = {t["target_id"]: t for t in d["targets"]}


def main() -> int:
    import psycopg

    dsn = os.environ.get(
        "CORPUS_DSN", "postgresql://postgres:postgres@localhost:5432/e6_holdout_corpus"
    )
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for tid, (build_pre, quote) in CASES.items():
            print(f"\n===== {tid} =====")
            t = targets[tid]
            delivered = set(t.get("delivered_locators") or [])
            cur.execute(
                "SELECT build_id FROM corpus.corpus_builds WHERE build_id LIKE %s",
                (build_pre + "%",),
            )
            hit = cur.fetchone()
            if not hit:
                print(f"  !! 找不到 build_id 前缀 {build_pre}")
                continue
            full_build = hit[0]
            cur.execute(
                "SELECT chunk_id, kind, unit_refs FROM corpus.corpus_chunks "
                "WHERE build_id = %s ORDER BY chunk_id",
                (full_build,),
            )
            chunk_rows = cur.fetchall()
            # 装配每个 chunk 的文本：unit_refs -> units.clean_view（与 compact 视图一致）
            all_unit_ids = sorted({u for _c, _k, refs in chunk_rows for u in (refs or [])})
            cur.execute(
                "SELECT unit_id, clean_view FROM corpus.corpus_units "
                "WHERE build_id = %s AND unit_id = ANY(%s)",
                (full_build, all_unit_ids),
            )
            unit_text = {uid: (cv or "") for uid, cv in cur.fetchall()}
            rows = [
                (cid, kind, "".join(unit_text.get(u, "") for u in (refs or [])))
                for cid, kind, refs in chunk_rows
            ]
            qn = norm(quote)
            # 1) 整条命中的 chunk
            whole = [cid for cid, _k, text in rows if qn in norm(text or "")]
            # 2) 分词级：找覆盖全部 token 的最小 chunk 组合
            toks = [norm(x) for x in re.split(r"\s+", quote.strip()) if len(norm(x)) >= 2]
            covering = [cid for cid, _k, text in rows if all(tok in norm(text or "") for tok in toks)]
            # 3) 逐 token 分布（前 8 个未命中整条的 token 落在哪些 chunk）
            print(f"  chunks 总数: {len(rows)}, delivered: {len(delivered)}")
            print(f"  整条命中 chunk: {whole}")
            print(f"  全 token 覆盖 chunk: {covering[:6]}")
            if not whole and not covering:
                # 找出缺失 token 及其所在 chunk
                miss = [(tok, [cid for cid, _k, text in rows if tok in norm(text or "")][:4]) for tok in toks]
                bad = [(tok, locs) for tok, locs in miss if not locs]
                print(f"  缺失 token 数: {len(bad)} / {len(toks)}")
                for tok, locs in bad[:8]:
                    print(f"    token='{tok}' 不在任何 chunk")
                # 检查引文是否跨相邻 chunk（每个 token 有落点但分散）
                spread = {}
                for tok, locs in miss:
                    if locs:
                        spread.setdefault(locs[0], 0)
                        spread[locs[0]] += 1
                top = sorted(spread.items(), key=lambda kv: -kv[1])[:5]
                print(f"  token 分布 top chunk: {top}")
                for cid, _cnt in top:
                    mark = " <== delivered" if cid in delivered else " <== NOT delivered"
                    print(f"    {cid}{mark}")
            else:
                inc = [cid for cid in (whole or covering) if cid in delivered]
                print(f"  其中在 delivered 集合内: {inc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
