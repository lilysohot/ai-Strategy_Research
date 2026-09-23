"""D2 立项前置：表格来源注聚合的**三条件精化扫描**（只读）。

背景：industry-008 a-3/a-5 引用的注1（ord518，kept，page:10）排 doc 内 47/120，
超出 `pool_cap=24` ⇒ 不在任何证据带内 ⇒ 两条目标同时 fail ⇒ industry 7/8。
候选修法 = `cross_boundary` 扩展「表格来源注聚合」（仿 r4u，免重摄入）。

本脚本回答"这个谓词到底会动到什么"，按 r4u 的三层扫描法：
  L1 裸谓词：kept + 段首为「资料来源 / 注N / 注： / 数据来源 / 说明：」
  L2 精化一：段内**含说明性分句**（注N：/ 注：/ 备注：/ 口径）——排除纯来源标注
  L3 精化二（本脚本重点）：同页 + 上方紧邻（垂直间距 < y_gap）确有 kept **表格行**单元
     ⇒ 只有"表格的口径脚注"才聚合，figure/孤立注释不聚合

口径：只读 PG（`i2_sandbox_corpus`，corpus schema 零写入）、0 model calls、不改任何字节。
用法： uv run python d2_footnote_scan.py [--no-write] [--y-gap 12]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
HERE = Path(__file__).resolve().parent
NON_SEMANTIC_FIELDS = ("generated_at",)

LEAD = re.compile(r"^\s*(资料来源|注\s*[0-9１-９]|注\s*[:：]|数据来源|说明\s*[:：])")
EXPLAIN = re.compile(r"(注\s*[0-9１-９]\s*[:：]|注\s*[:：]|备注\s*[:：]|口径)")
DEFAULT_Y_GAP = 12.0


def write_once(name: str, value) -> None:
    path = HERE / name
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        o = {k: v for k, v in old.items() if k not in NON_SEMANTIC_FIELDS}
        n = {k: v for k, v in value.items() if k not in NON_SEMANTIC_FIELDS}
        if json.dumps(o, sort_keys=True, default=str) == json.dumps(n, sort_keys=True, default=str):
            print(f"[write-once] {name} 语义逐字段一致 → 保留原产物字节")
            return
        diff = sorted({k for k in set(o) | set(n) if o.get(k) != n.get(k)})
        raise RuntimeError(f"write-once conflict: {name}; 差异字段={diff}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")
    print(f"[write-once] {name} 写入 {path}")


def main() -> int:
    import psycopg

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--y-gap", type=float, default=DEFAULT_Y_GAP)
    args = ap.parse_args()

    dsn = "postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus"
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT 1")
        cur = conn.cursor()
        cur.execute("SELECT current_database()")
        db = cur.fetchone()[0]
        if db != "i2_sandbox_corpus":
            raise RuntimeError(f"守卫失败：当前库 {db}")
        cur.execute(
            """SELECT u.build_id, u.ordinal, u.kind, u.raw_text,
                      u.location->>'page' AS page, u.location->'bbox' AS bbox
               FROM corpus.corpus_units u
               WHERE u.status = 'kept'
                 AND u.build_id IN (SELECT active_build_id FROM corpus.corpus_publications
                                    WHERE active_build_id IS NOT NULL)
               ORDER BY u.build_id, u.ordinal"""
        )
        rows = cur.fetchall()

    def y_of(bbox, idx: int) -> float | None:
        try:
            return float(list(bbox)[idx])
        except (TypeError, ValueError, IndexError):
            return None

    by_build: dict[str, list] = defaultdict(list)
    for build_id, ordinal, kind, raw, page, bbox in rows:
        by_build[build_id].append({
            "ordinal": ordinal, "kind": kind, "text": raw or "", "page": page,
            "y0": y_of(bbox, 1), "y1": y_of(bbox, 3),
        })

    l1, l2, l3 = [], [], []
    pairs: list[dict] = []
    for build_id, units in sorted(by_build.items()):
        units.sort(key=lambda u: u["ordinal"])
        for u in units:
            if not LEAD.match(u["text"]):
                continue
            l1.append((build_id, u["ordinal"]))
            if not EXPLAIN.search(u["text"]):
                continue
            l2.append((build_id, u["ordinal"]))
            # L3：同页 + 版面位于注段**上方**的 kept 表格行，且下沿与注段上沿间距 < y_gap。
            # ⚠ 只能用 bbox 的 y 判上下：**ordinal 序 ≠ 版面序**（本文档注段 ord518 的
            # ordinal 就排在表格单元 ord519+ 之前，但版面在表格下方）。
            best = None
            for v in units:
                if v["page"] != u["page"]:
                    continue
                if v["kind"] != "table_row":
                    continue
                if v["y1"] is None or u["y0"] is None:
                    continue
                gap = u["y0"] - v["y1"]
                if gap < 0 or gap >= args.y_gap:
                    continue
                if best is None or gap < best["gap"]:
                    best = {"anchor_ordinal": v["ordinal"], "gap": round(gap, 2),
                            "anchor_kind": v["kind"],
                            "anchor_text": v["text"][:60]}
            if best is None:
                continue
            l3.append((build_id, u["ordinal"]))
            pairs.append({
                "build": build_id[:10], "page": u["page"],
                "note_ordinal": u["ordinal"], "y_gap_pt": best["gap"],
                "anchor_ordinal": best["anchor_ordinal"],
                "anchor_text": best["anchor_text"],
                "note_text": u["text"][:110],
            })

    target = next((p for p in pairs if p["build"] == "1227c2a34d" and p["note_ordinal"] == 518), None)
    report = {
        "artifact": "d2-footnote-scan",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications（8 builds）",
        "mode": "只读 PG、0 model calls、不改任何字节；r4u 三层扫描法",
        "predicate": {
            "L1_lead": "kept 且段首为 资料来源 / 注N / 注： / 数据来源 / 说明：",
            "L2_explanatory": "段内含 注N：/注：/备注：/口径 说明性分句（排除纯来源标注）",
            "L3_anchored": f"同页 + 上方紧邻 kept table_row（垂直间距 < {args.y_gap}pt）",
        },
        "counts": {
            "active_kept_units": len(rows),
            "L1_lead": len(l1),
            "L2_explanatory": len(l2),
            "L3_anchored": len(l3),
            "sources_affected_L3": len({b for b, _ in l3}),
        },
        "per_source_L3": dict(Counter(b[:10] for b, _ in l3)),
        "per_source_L2": dict(Counter(b[:10] for b, _ in l2)),
        "pairs": pairs,
        "industry008_ord518": {
            "in_L3_pairs": target is not None,
            "pair": target,
            "note": "industry-008 a-3/a-5 所引注1 所在单元；必须命中，否则谓词不成立",
        },
    }
    print(json.dumps({k: v for k, v in report.items() if k != "pairs"}, ensure_ascii=False, indent=2))
    print(f"\n--- 配对清单（{len(pairs)} 条）---")
    for p in pairs:
        print(f"  {p['build']} p{p['page']} 注ord{p['note_ordinal']} ← 表ord{p['anchor_ordinal']} "
              f"(Δ{p['y_gap_pt']}pt) | {p['note_text'][:56]!r}")

    if not args.no_write:
        write_once("d2-footnote-scan.json", report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
