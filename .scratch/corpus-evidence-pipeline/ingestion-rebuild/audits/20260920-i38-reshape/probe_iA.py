"""议题 A 可行性探针（只读 PG）：11 条引文在当前 reader-pdf-5 语料下的连续块覆盖区间。

回答三个设计问题：
1. 每条引文能否被**连续块区间** [A, B]（按原文序拼接、去空白后包含）覆盖？区间多长？
2. 起始块 A 是否在 OR 词元候选池内？（若 A 不在池内，选择层将无法"命中→展开"）
3. 引文 head/tail 在全块序列中的位置，与 OR 命中池的间距（评估"④ 尾段不在池内"的实际距离）。

做法：对每条 target 所在 build 取全部 chunk（按 min unit ordinal 排原文序），
用去空白前缀串做 O(1) 区间文本查询；对每个起始块 A 二分求最短覆盖 B。
不写任何产物，仅 stdout。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I33 = BASE / "audits/20260920-i33-calibration"
I37 = BASE / "audits/20260920-i37-fullchain-backtest"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

TARGETS = [
    ("company-004", "e2"), ("company-004", "a-2"), ("company-004", "a-3"),
    ("company-005", "e2"), ("company-005", "e3"),
    ("company-008", "a-2"), ("company-008", "a-3"), ("company-008", "a-5"),
    ("macro-002", "e4"), ("macro-003", "a-2"), ("macro-003", "a-4"),
]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> int:
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")

    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import build_handle, chunk_locator, fetch_verbatim
    from plugins.corpus.preparation.search_pg import search_chunks
    from plugins.corpus.scoring import gold_from_records
    import psycopg

    questions = {q.query_id: q for q in gold_from_records(records)}
    ident = json.loads((I37 / "source-identity-map.json").read_text())
    alias_to_sha = {alias: sha for sha, alias in ident["aliases"].items()}
    rows = {(r["query_id"], r["target_id"]): r
            for r in json.loads((I37 / "diagnostics.json").read_text())}

    results = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        # 每 build 全量 chunks 原文序缓存
        build_chunks: dict[str, list[tuple[str, str]]] = {}

        def ordered_chunks(build_id: str) -> list[tuple[str, str]]:
            if build_id in build_chunks:
                return build_chunks[build_id]
            rows = conn.execute(
                "SELECT chunk_id, unit_refs FROM corpus.corpus_chunks WHERE build_id = %s",
                (build_id,)).fetchall()

            def min_ordinal(refs: list) -> int:
                vals = []
                for ref in refs or []:
                    try:
                        vals.append(int(str(ref).rsplit(":", 1)[-1]))
                    except ValueError:
                        pass
                return min(vals) if vals else 10**9

            ordered = sorted(
                ((str(r[0]), min_ordinal(r[1])) for r in rows), key=lambda item: item[1])
            chunks = []
            for cid, _ in ordered:
                got = fetch_verbatim(dsn, build_handle(build_id), chunk_locator(cid))
                chunks.append((cid, norm(got.text)))
            build_chunks[build_id] = chunks
            return chunks

        for qid, tid in TARGETS:
            row = rows[(qid, tid)]
            question = questions[qid]
            sha = alias_to_sha[row["source_id"]]
            build_row = conn.execute(
                "SELECT active_build_id FROM corpus.corpus_publications "
                "WHERE source_id = %s AND active_build_id IS NOT NULL", (sha,)).fetchone()
            build_id = build_row[0]

            lexemes = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(question.question),)).fetchone()[0]
            query = " OR ".join('"' + term.replace('"', " ") + '"' for term in lexemes)
            hits = search_chunks(dsn, query, limit=2000)
            pool = {h.chunk_id for h in hits if h.source_id == sha}

            ordered = ordered_chunks(build_id)
            chunks = [t for _, t in ordered]
            quote = norm(row["quote"])
            # 前缀串：引文在文档 concat 中首次出现位置 → 精确覆盖区间 [A, B]
            pref = [""]
            for c in chunks:
                pref.append(pref[-1] + c)
            pos = pref[-1].find(quote)
            best = None
            span = None
            a_in_pool = b_in_pool = "?"
            pool_inside = 0
            nearest_neighbor = None
            if pos >= 0:
                end = pos + len(quote) - 1
                a = next(i for i in range(len(chunks)) if len(pref[i + 1]) > pos)
                b = next(i for i in range(len(chunks)) if len(pref[i + 1]) > end)
                best = (a, b)
                span = b - a + 1
                a_in_pool = ordered[a][0] in pool
                b_in_pool = ordered[b][0] in pool
                pool_inside = sum(1 for i in range(a, b + 1) if ordered[i][0] in pool)
                nearest = min(
                    (abs(i - a) for i in range(a, b + 1) if ordered[i][0] in pool), default=None)
                nearest_b = min(
                    (abs(i - b) for i in range(a, b + 1) if ordered[i][0] in pool), default=None)
                nearest_neighbor = max(nearest, nearest_b) if nearest is not None else None
            results.append({
                "query_id": qid, "target_id": tid,
                "quote_len": len(quote), "chunks": len(chunks), "pool": len(pool),
                "cover": best, "span": span,
                "start_in_pool": a_in_pool, "end_in_pool": b_in_pool,
                "pool_inside": pool_inside, "max_neighbor": nearest_neighbor,
            })
            print(f"{qid} {tid}: len={len(quote)} chunks={len(chunks)} pool={len(pool)} "
                  f"cover=[{best}] span={span} start_in_pool={a_in_pool} end_in_pool={b_in_pool} "
                  f"pool_inside={pool_inside} max_neighbor={nearest_neighbor}")
    (HERE / "probe-iA-coverage.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
