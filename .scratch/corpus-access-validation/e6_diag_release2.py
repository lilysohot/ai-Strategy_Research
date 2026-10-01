"""只读 dry-run：为 9 份材料构造 GapReview 并逐个 apply_gap_review 校验可行性。

对每份材料：
- blocking gaps 来自 e6-holdout-build.json 的 quality_report.gap_regions（排除 image_region_small）；
- required_locators = 该材料所有目标证据页（page:N），证据页来自整条 kept 命中；
- 若证据页与缺口页相交（PAGE 级 _disjoint 失败），尝试 region schema：
    从 kept 单元 raw_text 提取实际保留文本作 region_targets quotes，
    并检查单元 bbox 与该页图像不相交。
输出每份材料的放行可行性结论。本脚本只读、不写入凭证。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
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

import pymupdf  # noqa: E402

from plugins.corpus.preparation.contract import UnitStatus  # noqa: E402
from plugins.corpus.preparation.gaps import blocking_gaps  # noqa: E402
from plugins.corpus.preparation.gap_review import GapReview, SCHEMA_REV, REGION_SCHEMA_REV  # noqa: E402

BUILD = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
PACKET = json.loads((HERE / "e6-human-gap-review-packet.json").read_text(encoding="utf-8"))
ARCHIVE = HERE / "e6-holdout-archive"

WS = __import__("re").compile(r"\s+")


def norm(s):
    return WS.sub("", s or "")


def disjoint(box, image):
    x0, y0, x1, y1 = box
    i0, j0, i1, j1 = image
    return x1 < i0 or i1 < x0 or y1 < j0 or j1 < y0


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)
    blocked = [s for s in BUILD["sources"] if s.get("outcome") == "blocked_by_publish_gate"]
    by_sample = {m["sample_id"]: m for m in PACKET["materials"]}
    rev = "e6-human-gap-review"

    for src in blocked:
        sid = src["sample_id"]
        bid = src["build_id"]
        source_id = src["source_id"]
        print(f"\n########## {sid} :: {bid[:12]} ##########")
        gaps = [g for g in src["quality_report"]["gap_regions"] if "image_region_small" not in g]
        gap_pages = sorted({int(g.split(":page:")[1]) for g in gaps})

        # 证据页：每个目标整条 kept 命中的页面（用归一化比对）
        units = conn.execute(
            "select unit_id, kind, status, raw_text, location "
            "from corpus.corpus_units where build_id = %s",
            (bid,),
        ).fetchall()
        kept = [u for u in units if u[2] == "kept"]
        mat = by_sample[sid]
        evidence_pages = set()
        evidence_by_target = {}
        for tgt in mat["blocked_targets"]:
            qn = norm(tgt.get("expected_quote") or "")
            hits = sorted({u[4].get("page") for u in kept if qn and qn in norm(u[3] or "")})
            if not hits:
                toks = [t for t in WS.split(tgt.get("expected_quote") or "") if len(norm(t)) >= 4][:3]
                hits = sorted({u[4].get("page") for u in kept if any(tok and norm(tok) in norm(u[3] or "") for tok in toks)})
            evidence_by_target[tgt["target_id"]] = hits
            evidence_pages.update(hits)
        print(f"  blocking gaps: {len(gaps)}; gap_pages={gap_pages}")
        print(f"  证据页={sorted(evidence_pages)}")
        for tid, pages in evidence_by_target.items():
            print(f"    {tid}: {pages}")

        overlap = sorted(evidence_pages & set(gap_pages))
        print(f"  证据页∩缺口页: {overlap}")

        req_locators = [f"page:{p}" for p in sorted(evidence_pages)]
        # 尝试 PAGE 级
        page_ok = not overlap
        if page_ok:
            print(f"  => PAGE 级可放行: required_locators={req_locators}")
        else:
            print(f"  => PAGE 级冲突，尝试 region schema")
            # region: 对每个 overlap 页，从 kept 单元找含证据文本的单元，提取保留文本为 quote
            region_targets = {}
            region_ok = True
            for pg in overlap:
                quotes = []
                pg_units = [u for u in kept if u[4].get("page") == pg]
                images = []
                pdf = ARCHIVE / source_id[:2] / f"{source_id}.pdf"
                if not pdf.exists():
                    pdf = None
                if pdf is None:
                    print(f"    page {pg}: 找不到 PDF {src['file']}")
                    region_ok = False
                    break
                with pymupdf.open(pdf) as doc:
                    p = doc[pg - 1]
                    images = [tuple(i["bbox"]) for i in p.get_image_info()]
                # 取该页每个目标引文的实际保留文本
                for tid, pages in evidence_by_target.items():
                    if pg not in pages:
                        continue
                    tgt = next(t for t in mat["blocked_targets"] if t["target_id"] == tid)
                    qn = norm(tgt.get("expected_quote") or "")
                    # 找该页 kept 单元中包含引文最多内容的
                    best = None
                    for u in pg_units:
                        un = norm(u[3] or "")
                        # 单元 raw_text 去空白后包含引文全部片段？
                        frags = [f for f in qn.split("；") if len(f) >= 4]
                        cov = sum(1 for f in frags if f in un) / max(1, len(frags))
                        if cov >= 0.9 and (best is None or cov > best[0]):
                            best = (cov, u)
                    if best:
                        u = best[1]
                        box = tuple(u[4].get("bbox"))
                        bad = [b for b in images if not disjoint(box, b)]
                        # 用单元 raw_text 本身（源页真实保留文本）作 quote
                        q = (u[3] or "").strip()
                        quotes.append(q[:200])
                        if bad:
                            print(f"      page {pg} {tid}: 单元 {u[0]} 与 {len(bad)} 个图像相交 -> region 失败")
                            region_ok = False
                        else:
                            print(f"      page {pg} {tid}: 单元 {u[0]} bbox 与图像不相交 OK (quote {len(q)}字)")
                    else:
                        print(f"      page {pg} {tid}: 无 ≥90% 覆盖单元 -> region 失败")
                        region_ok = False
                if quotes:
                    region_targets[str(pg)] = quotes
            if region_ok and region_targets:
                print(f"  => region schema 可放行: required_locators={req_locators} region_pages={list(region_targets)}")
            else:
                print(f"  => region 不可行，需要替代路径")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
