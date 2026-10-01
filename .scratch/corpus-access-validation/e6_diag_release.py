"""只读：预检验证 9 份材料放行 gap-review 的可行性。

对每份材料：
1) 列出全部 blocking gap（key 列表）；
2) 每个被阻断目标 -> 证据页 + 引文是否单 kept 单元保留（含 bbox + raw_text 长度）；
3) 对证据页=缺口页的情形，检查单元 bbox 与该页图像 bbox 是否不相交（region 证明可行性）。
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = "e6_holdout_corpus"
os.environ.pop("PGOPTIONS", None)

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

BUILD = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
PACKET = json.loads((HERE / "e6-human-gap-review-packet.json").read_text(encoding="utf-8"))

RE = __import__("re")
WS = __import__("re").compile(r"\s+")


def norm(s):
    return WS.sub("", s or "")


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)

    blocked = [s for s in BUILD["sources"] if s.get("outcome") == "blocked_by_publish_gate"]
    by_sample = {m["sample_id"]: m for m in PACKET["materials"]}
    for src in blocked:
        sid = src["sample_id"]
        bid = src["build_id"]
        # blocking gaps = quality_report.gap_regions 中非 image_region_small 的
        gaps = [g for g in src["quality_report"]["gap_regions"] if "image_region_small" not in g]
        gap_pages = sorted({int(g.split(":page:")[1]) for g in gaps})
        print(f"\n===== {sid} :: build {bid[:12]} =====")
        print(f"  blocking gaps ({len(gaps)}): {gaps}")
        print(f"  gap_pages: {gap_pages}")
        mat = by_sample[sid]
        # 每个目标证据页与引文
        for tgt in mat["blocked_targets"]:
            tgtid = tgt["target_id"]
            q = tgt.get("expected_quote") or ""
            qn = norm(q)
            # 找 kept 单元中含引文整条的
            rows = conn.execute(
                "select unit_id, kind, status, raw_text, location "
                "from corpus.corpus_units where build_id = %s "
                "and status = 'kept' and raw_text is not null",
                (bid,),
            ).fetchall()
            full_hits = [(r[0], r[4].get("page"), r[3]) for r in rows if qn and qn in norm(r[3])]
            print(f"  target {tgtid}: 引文整条 kept 命中 {len(full_hits)} 处: "
                  f"{[(h[0], h[1]) for h in full_hits[:4]]}")
            if not full_hits:
                # 按显著 token 找
                toks = [t for t in WS.split(q) if len(norm(t)) >= 4][:5]
                hit_units = [r for r in rows if any(t and norm(t) in norm(r[3]) for t in toks)]
                pages = sorted({r[4].get("page") for r in hit_units})
                print(f"    (整条不匹配) token 命中单元 {len(hit_units)} 个, 页 {pages}")
                for r in hit_units[:3]:
                    print(f"      [{r[0]}] page={r[4].get('page')} kind={r[1]} "
                          f"len={len(r[3])} bbox={r[4].get('bbox')}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
