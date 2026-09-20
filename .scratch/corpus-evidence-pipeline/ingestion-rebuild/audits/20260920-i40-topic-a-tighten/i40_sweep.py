"""i40 扫描：跨度上限 A/B/C 三种拆分方案 → 11/11 保持 + 体积上界可证。

只读 PG + 0 model_calls。输出 i40-sweep.json（新目录首写，无 write-once 冲突）。
"""
from __future__ import annotations

import importlib.util
import json
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
G, K = 1, 1
BAND_CAP = 8

SENSITIVITY = [(1, 1), (1, 2), (2, 2), (2, 3)]
# 方案 A/B/C 的候选参数
SWEEP = [
    ("width", 16), ("width", 24), ("width", 32), ("width", 48),
    ("pool", 8), ("pool", 16), ("pool", 24), ("pool", 32),
    ("ratio", 0.15), ("ratio", 0.25), ("ratio", 0.30), ("ratio", 0.40),
]


def cap_split(bands, score_by_pos, n, mode, cap):
    """将超限簇拆为子带；子带锚定池块，两端各扩展 K。

    - width: 子带区间宽 ≤ cap 块；cap 由调用方换算（ratio 模式 = ratio*n）。
    - pool:  子带内池块数 ≤ cap。
    返回新带列表（每带 {start,end,score,pool}）。
    """
    out = []
    for band in bands:
        bp = band["pool"]
        if mode == "pool":
            if len(bp) <= cap:
                out.append(band)
                continue
            for i in range(0, len(bp), cap):
                group = bp[i:i + cap]
                out.append({"start": max(0, group[0] - K), "end": min(n - 1, group[-1] + K),
                            "score": max(score_by_pos[p] for p in group), "pool": list(group)})
        elif mode in ("width", "ratio"):
            width = band["end"] - band["start"] + 1
            if width <= cap:
                out.append(band)
                continue
            group = [bp[0]]
            for p in bp[1:]:
                end = min(n - 1, p + K)
                start = max(0, group[0] - K)
                if end - start + 1 <= cap:
                    group.append(p)
                else:
                    out.append({"start": start, "end": min(n - 1, group[-1] + K),
                                "score": max(score_by_pos[x] for x in group), "pool": list(group)})
                    group = [p]
            if group:
                out.append({"start": max(0, group[0] - K), "end": min(n - 1, group[-1] + K),
                            "score": max(score_by_pos[x] for x in group), "pool": list(group)})
    return out


def or_query(conn, question: str) -> str:
    lexemes = conn.execute(
        "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
        (normalize_search_text(question),)).fetchone()[0]
    return " OR ".join('"' + t.replace('"', ' ') + '"' for t in lexemes)


def main() -> int:
    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets
                             if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources
                       if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}

        build_cache: dict[str, tuple[list[str], dict[str, dict]]] = {}

        def ordered_meta(bid: str):
            if bid not in build_cache:
                build_cache[bid] = i39.load_build_chunks(conn, bid)
            return build_cache[bid]

        # 每目标每 (mode, cap) 的 cover 子带判定 + 全题体积统计
        rows = []
        for qid, tid in i39.TOPIC_A_TARGETS:
            question = next(q for q in questions if q.query_id == qid)
            target = next(t for t in question.evidence_targets if t.target_id == tid)
            pub = alias_to_source.get(target.source_id or "")
            build_id = sources.get(pub) if pub else None
            if not build_id:
                raise RuntimeError(f"no build for {qid} {tid}")
            ordered, meta = ordered_meta(build_id)
            chunks = [i39.norm(meta[cid]["text"]) for cid in ordered]
            quote = i39.norm(target.quote)
            pref = [""]
            for c in chunks:
                pref.append(pref[-1] + c)
            pos = pref[-1].find(quote)
            if pos < 0:
                raise RuntimeError(f"quote not found for {qid} {tid}")
            end = pos + len(quote) - 1
            a = next(i for i in range(len(chunks)) if len(pref[i + 1]) > pos)
            b = next(i for i in range(len(chunks)) if len(pref[i + 1]) > end)
            n = len(ordered)

            query = or_query(conn, question.question)
            hits = search_chunks(dsn, query, limit=2000)
            pos_of = {cid: i for i, cid in enumerate(ordered)}
            pool = sorted(pos_of[h.chunk_id] for h in hits
                          if h.source_id == pub and h.chunk_id in pos_of)
            score = {pos_of[h.chunk_id]: h.score for h in hits
                     if h.source_id == pub and h.chunk_id in pos_of}

            base = i39.form_bands(pool, score, n, G, K)
            base_rank = i39.rank_bands(base)
            base_cov = next((i for i, band in enumerate(base)
                             if band["start"] <= a and b <= band["end"]), None)

            entry = {"query_id": qid, "target_id": tid, "cover": [a, b], "n": n,
                     "base": None}
            if base_cov is not None:
                entry["base"] = {
                    "width": base[base_cov]["end"] - base[base_cov]["start"] + 1,
                    "pool": len(base[base_cov]["pool"]), "rank": base_rank[base_cov]}
            entry["by_param"] = {}
            for mode, cap in SWEEP:
                eff_cap = int(cap * n) if mode == "ratio" else cap
                bands = cap_split(base, score, n, mode, eff_cap)
                if not bands:
                    entry["by_param"][f"{mode}:{cap}"] = {"coverable": False}
                    continue
                ranking = i39.rank_bands(bands)
                cov = next((i for i, band in enumerate(bands)
                            if band["start"] <= a and b <= band["end"]), None)
                if cov is None:
                    entry["by_param"][f"{mode}:{cap}"] = {"coverable": False,
                                                          "n_bands": len(bands)}
                    continue
                rank = ranking[cov]
                sel = rank <= BAND_CAP
                splice = None
                if sel:
                    band = bands[cov]
                    text = "\n".join(meta[ordered[p]]["text"]
                                     for p in range(band["start"], band["end"] + 1))
                    splice = quote in i39.norm(text)
                entry["by_param"][f"{mode}:{cap}"] = {
                    "coverable": True, "rank": rank, "selected": sel,
                    "splice_contains_quote": splice,
                    "cover_band_span": [bands[cov]["start"], bands[cov]["end"]],
                    "cover_band_width": bands[cov]["end"] - bands[cov]["start"] + 1,
                    "cover_band_pool": len(bands[cov]["pool"]),
                    "n_bands": len(bands)}
            rows.append(entry)

        # 全题体积统计：对每个有答案题、每来源（selected top-8）计算选中块数与最大带宽
        vol = {}
        for mode, cap in SWEEP:
            vols = []
            max_w = 0
            max_union = 0
            max_ratio_doc = (None, 0.0)
            for q in questions:
                if q.answer_existence is AnswerExistence.NO_ANSWER:
                    continue
                query = or_query(conn, q.question)
                hits = search_chunks(dsn, query, limit=2000)
                for pub in set(h.source_id for h in hits):
                    build_id = sources.get(pub)
                    if not build_id:
                        continue
                    ordered, meta = ordered_meta(build_id)
                    pos_of = {cid: i for i, cid in enumerate(ordered)}
                    pool = sorted(pos_of[h.chunk_id] for h in hits
                                  if h.source_id == pub and h.chunk_id in pos_of)
                    if not pool:
                        continue
                    score = {pos_of[h.chunk_id]: h.score for h in hits
                             if h.source_id == pub and h.chunk_id in pos_of}
                    n = len(ordered)
                    eff_cap = int(cap * n) if mode == "ratio" else cap
                    bands = cap_split(i39.form_bands(pool, score, n, G, K), score, n,
                                      mode, eff_cap)
                    ranking = i39.rank_bands(bands)
                    selected = [bands[i] for i in ranking if ranking[i] <= BAND_CAP]
                    widths = [b["end"] - b["start"] + 1 for b in selected]
                    covered = set()
                    for b in selected:
                        covered.update(range(b["start"], b["end"] + 1))
                    max_w = max(max_w, max(widths) if widths else 0)
                    max_union = max(max_union, len(covered))
                    ratio = len(covered) / n
                    if ratio > max_ratio_doc[1]:
                        max_ratio_doc = (q.query_id, ratio)
                    vols.append({"q": q.query_id, "n": n, "selected_bands": len(selected),
                                 "sum_widths": sum(widths), "union": len(covered),
                                 "ratio": round(ratio, 4)})
            vol[f"{mode}:{cap}"] = {"max_width": max_w, "max_union": max_union,
                                    "worst_ratio": {"q": max_ratio_doc[0],
                                                    "ratio": round(max_ratio_doc[1], 4)},
                                    "per_doc": vols}

        (HERE / "i40-sweep.json").write_text(
            json.dumps({"sensitivity_G_K": SENSITIVITY, "targets": rows, "volume": vol},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # stdout 摘要
        for mode, cap in SWEEP:
            kept = sum(1 for r in rows
                       for k, v in r["by_param"].items()
                       if k == f"{mode}:{cap}" and v.get("selected")
                       and v.get("splice_contains_quote"))
            v = vol[f"{mode}:{cap}"]
            print(f"{mode:5s} cap={cap:<5} 11-kept={kept}/11 "
                  f"max_width={v['max_width']} max_union={v['max_union']} "
                  f"worst_ratio={v['worst_ratio']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
