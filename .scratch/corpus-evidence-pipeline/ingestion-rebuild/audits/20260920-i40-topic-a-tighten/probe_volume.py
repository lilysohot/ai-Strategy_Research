"""i40 探针：量化带体积，为跨度上限（A/B/C）选型提供数据。

只读 PG + 0 model_calls。输出到 stdout（不写产物文件）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I39 = BASE / "audits/20260920-i39-topic-a"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE / "audits/20260920-i33-calibration"))
sys.path.insert(0, str(I39))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


i39 = load_module("i39_band", I39 / "i39_band.py")
release = load_module("i31_region_release",
                      BASE / "audits/20260920-i31-region-review/release.py")
dsn = release.connect()

from plugins.corpus.scoring import AnswerExistence, gold_from_records  # noqa: E402
from plugins.corpus.preparation.chunk import normalize_search_text  # noqa: E402
from plugins.corpus.preparation.search_pg import _check_target, search_chunks  # noqa: E402
import psycopg  # noqa: E402

SANDBOX = "i2_sandbox_corpus"

loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
questions = gold_from_records(records)

G, K = 1, 1


def or_query(conn, question: str) -> str:
    lexemes = conn.execute(
        "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
        (normalize_search_text(question),)).fetchone()[0]
    return " OR ".join('"' + t.replace('"', ' ') + '"' for t in lexemes)


with psycopg.connect(dsn, autocommit=True) as conn:
    _check_target(conn, SANDBOX)
    sources = dict(conn.execute(
        "SELECT source_id, active_build_id FROM corpus.corpus_publications "
        "WHERE active_build_id IS NOT NULL").fetchall())
    build_cache: dict[str, tuple[list[str], dict[str, dict]]] = {}

    def ordered_meta(bid: str):
        if bid not in build_cache:
            build_cache[bid] = i39.load_build_chunks(conn, bid)
        return build_cache[bid]

    # 1) 每文档带分布（G=1/K=1，未截断）：宽度与池块数
    print("=== per-doc band distribution (G=1,K=1, uncapped) ===")
    per_doc = {}
    for q in questions:
        if q.answer_existence is AnswerExistence.NO_ANSWER:
            continue
        query = or_query(conn, q.question)
        hits = search_chunks(dsn, query, limit=2000)
        by_src: dict[str, list] = {}
        for h in hits:
            by_src.setdefault(h.source_id, []).append(h)
        for src, hh in by_src.items():
            build_id = hh[0].build_id
            ordered, meta = ordered_meta(build_id)
            pos_of = {cid: i for i, cid in enumerate(ordered)}
            pool = sorted(pos_of[h.chunk_id] for h in hh)
            score = {pos_of[h.chunk_id]: h.score for h in hh}
            bands = i39.form_bands(pool, score, len(ordered), G, K)
            widths = [b["end"] - b["start"] + 1 for b in bands]
            pool_n = [len(b["pool"]) for b in bands]
            per_doc.setdefault(src, []).append({
                "q": q.query_id, "doc": len(ordered), "pool": len(pool),
                "n_bands": len(bands),
                "max_width": max(widths) if widths else 0,
                "max_width_band": (max(range(len(bands)), key=lambda i: widths[i])
                                   if widths else None),
                "max_pool": max(pool_n) if pool_n else 0,
                "widths": widths,
                "pool_ns": pool_n,
            })
    for src, lst in sorted(per_doc.items()):
        for e in lst:
            print(f"{e['q']} {src} doc={e['doc']} pool={e['pool']} bands={e['n_bands']} "
                  f"max_width={e['max_width']} max_pool={e['max_pool']}")
        top = sorted(lst, key=lambda e: -e["max_width"])
        if top:
            e = top[0]
            print(f"  >> {e['q']} max_width={e['max_width']} band_pool={e['pool_ns'][e['max_width_band']]}")

    # 2) 11 条目标：cover 簇的池块数（决定 POOL_CAP 可行性）
    print("\n=== 11 topic-a targets: pool count in cover cluster ===")
    for qid, tid in i39.TOPIC_A_TARGETS:
        question = next(q for q in questions if q.query_id == qid)
        target = next(t for t in question.evidence_targets if t.target_id == tid)
        # resolve source
        alias = None
        for a in question.relevant_sources:
            if target.source_id and target.source_id == a:
                alias = a
        if not alias and target.source_id:
            alias = target.source_id
        src = None
        for s in sources:
            if s.startswith(alias.rsplit("_", 1)[-1]):
                src = s
        if not src:
            print(f"{qid} {tid}: NO SOURCE")
            continue
        build_id = sources[src]
        ordered, meta = ordered_meta(build_id)
        chunks = [i39.norm(meta[cid]["text"]) for cid in ordered]
        quote = i39.norm(target.quote)
        pref = [""]
        for c in chunks:
            pref.append(pref[-1] + c)
        pos = pref[-1].find(quote)
        if pos < 0:
            print(f"{qid} {tid}: QUOTE NOT FOUND")
            continue
        end = pos + len(quote) - 1
        a = next(i for i in range(len(chunks)) if len(pref[i + 1]) > pos)
        b = next(i for i in range(len(chunks)) if len(pref[i + 1]) > end)
        query = or_query(conn, question.question)
        hits = search_chunks(dsn, query, limit=2000)
        pos_of = {cid: i for i, cid in enumerate(ordered)}
        pool = sorted(pos_of[h.chunk_id] for h in hits if h.source_id == src)
        score = {pos_of[h.chunk_id]: h.score for h in hits
                 if h.source_id == src and h.chunk_id in pos_of}
        bands = i39.form_bands(pool, score, len(ordered), G, K)
        cover_band = next((i for i, band in enumerate(bands)
                           if band["start"] <= a and b <= band["end"]), None)
        if cover_band is None:
            print(f"{qid} {tid}: NO COVER BAND")
            continue
        band = bands[cover_band]
        n_pool_in_cover = sum(1 for p in pool if band["start"] <= p <= band["end"])
        # minimal pool-count needed: pool blocks strictly between a and b
        between = [p for p in pool if a <= p <= b]
        print(f"{qid} {tid} cover=[{a},{b}] cluster_band=[{band['start']},{band['end']}] "
              f"width={band['end']-band['start']+1} cluster_pool={len(band['pool'])} "
              f"pool_in_cover={n_pool_in_cover} pool_between_a_b={len(between)}")
