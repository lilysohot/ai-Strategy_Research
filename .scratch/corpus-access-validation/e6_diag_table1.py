"""只读：table1 归因——引文所在 unit/chunk 与 delivered 集合比对。"""
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
norm = lambda s: WS.sub("", s or "")

BUILD_PRE = "bb6c4f161d46eee9"

d = json.loads((HERE / "e6-data-delivery-holdout-rerun.json").read_text(encoding="utf-8"))
t = {x["target_id"]: x for x in d["targets"]}["f3b28791-table1"]
quote = None
for line in (HERE / "samples.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    for tg in row.get("targets") or []:
        if tg.get("target_id") == "f3b28791-table1":
            quote = str(tg.get("verbatim_quote") or "")
            print("question:", row.get("question", "")[:80])
print("quote:", quote[:120], "...")
print("delivered:", len(t.get("delivered_locators") or []))

import psycopg

with psycopg.connect(os.environ["CORPUS_DSN"]) as conn, conn.cursor() as cur:
    cur.execute(
        "SELECT build_id FROM corpus.corpus_builds WHERE build_id LIKE %s", (BUILD_PRE + "%",)
    )
    build = cur.fetchone()[0]
    cur.execute(
        "SELECT chunk_id, kind, unit_refs FROM corpus.corpus_chunks "
        "WHERE build_id=%s ORDER BY chunk_id",
        (build,),
    )
    chunks = cur.fetchall()
    all_units = sorted({u for _c, _k, refs in chunks for u in (refs or [])})
    cur.execute(
        "SELECT unit_id, clean_view FROM corpus.corpus_units "
        "WHERE build_id=%s AND unit_id=ANY(%s)",
        (build, all_units),
    )
    utext = {u: cv or "" for u, cv in cur.fetchall()}
    ctext = {
        cid: "".join(utext.get(u, "") for u in (refs or [])) for cid, _k, refs in chunks
    }
    qn = norm(quote)
    toks = [norm(x) for x in re.split(r"\s+", quote.strip()) if len(norm(x)) >= 2]
    whole = [cid for cid, txt in ctext.items() if qn in norm(txt)]
    cover = [cid for cid, txt in ctext.items() if all(tk in norm(txt) for tk in toks)]
    delivered = set(t.get("delivered_locators") or [])
    print("整条命中 chunk:", whole)
    print("全token覆盖 chunk:", cover[:6])
    if not whole and not cover:
        miss = [(tk, [cid for cid, txt in ctext.items() if tk in norm(txt)][:4]) for tk in toks]
        bad = [(tk, locs) for tk, locs in miss if not locs]
        print(f"缺失 token: {len(bad)}/{len(toks)}")
        for tk, locs in bad[:10]:
            print(f"  '{tk[:40]}' 不在任何 chunk")
        spread = {}
        for tk, locs in miss:
            if locs:
                spread[locs[0]] = spread.get(locs[0], 0) + 1
        top = sorted(spread.items(), key=lambda kv: -kv[1])[:6]
        print("token 分布 top:")
        for cid, n in top:
            print(f"  {cid} x{n}{' <== delivered' if cid in delivered else ' <== NOT delivered'}")
    else:
        print("在 delivered 内:", [c for c in (whole or cover) if c in delivered])
