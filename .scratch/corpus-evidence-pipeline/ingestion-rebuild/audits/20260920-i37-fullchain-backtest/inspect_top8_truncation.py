"""只读核查：选项 ②（切块/证据选择 top-8 截断）是否真是 21 条 kept_page_not_selected 的成因。

对每条：文档排名（是否进 top-5）、该文档在候选池中的命中块数、
**含引文的块在该文档内的排名**、以及该排名是否 > 8（即被 top-8 截断）。
若排名 ≤ 8 却仍未选中，说明成因不是截断；若候选池内找不到，说明是召回的词元问题。
只读 PG（search + fetch），不写库、不改资产。
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  group_hits

MAX_FETCH_PER_DOC = 60


def load_module(name: str, path: Path):  # noqa: ANN201
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> None:
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")

    from plugins.corpus.preparation.chunk import normalize_search_text  # noqa: PLC0415
    from plugins.corpus.preparation.read_pg import (  # noqa: PLC0415
        build_handle,
        chunk_locator,
        fetch_verbatim,
    )
    from plugins.corpus.preparation.search_pg import search_chunks  # noqa: PLC0415
    from plugins.corpus.scoring import gold_from_records  # noqa: PLC0415
    import psycopg  # noqa: PLC0415

    questions = {q.query_id: q for q in gold_from_records(records)}
    ident = json.loads((HERE / "source-identity-map.json").read_text())
    alias_of = {sha: alias for sha, alias in ident["aliases"].items()}
    rows = [
        r
        for r in json.loads((HERE / "diagnostics.json").read_text())
        if r["bucket"] == "kept_page_not_selected"
    ]

    summary = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        for qid in sorted({r["query_id"] for r in rows}):
            question = questions[qid]
            lexemes = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(question.question),),
            ).fetchone()[0]
            query = " OR ".join('"' + term.replace('"', " ") + '"' for term in lexemes)
            hits = search_chunks(dsn, query, limit=2000)
            grouped = calibrate.group_hits(hits, 5, 8)
            doc_order = list(grouped)
            on_top5 = {alias_of.get(s, s): i + 1 for i, s in enumerate(doc_order)}
            print("=" * 92)
            print(f"Q {qid}  候选块={len(hits)}   top-5 文档={sorted(on_top5, key=lambda k: on_top5[k])}")
            for row in [x for x in rows if x["query_id"] == qid]:
                sha = next((s for s, a in alias_of.items() if a == row["source_id"]), None)
                if sha is None:
                    print(f"   {row['target_id']}: 别名无法解析到 sha，跳过")
                    continue
                doc_hits = [h for h in hits if h.source_id == sha]
                rank = None
                for i, hit in enumerate(doc_hits[:MAX_FETCH_PER_DOC], start=1):
                    got = fetch_verbatim(
                        dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id)
                    )
                    if norm(row["quote"]) in norm(got.text):
                        rank = i
                        break
                doc_rank = on_top5.get(row["source_id"])
                if rank is None:
                    verdict = f"候选池前{MAX_FETCH_PER_DOC}块内找不到（召回/切块口径问题）"
                elif rank > 8:
                    verdict = f">8，被 top-8 截断（截断说成立）"
                else:
                    verdict = "≤8 却仍未选中（截断说不成立，另有成因）"
                print(f"   {row['target_id']}: 文档排名={doc_rank} 该文档命中块={len(doc_hits)} "
                      f"含引文块排名={rank} → {verdict}")
                summary.append({
                    "query_id": qid, "target_id": row["target_id"],
                    "doc_rank": doc_rank, "doc_hits": len(doc_hits), "quote_chunk_rank": rank,
                })

    truncated = [s for s in summary if s["quote_chunk_rank"] and s["quote_chunk_rank"] > 8]
    inside = [s for s in summary if s["quote_chunk_rank"] and s["quote_chunk_rank"] <= 8]
    missing = [s for s in summary if s["quote_chunk_rank"] is None]
    no_doc = [s for s in summary if s["doc_rank"] is None]
    print("=" * 92)
    print(f"合计 {len(summary)} 条：被 top-8 截断 {len(truncated)} ｜ 排名≤8 仍未选中 {len(inside)} "
          f"｜ 候选池找不到 {len(missing)} ｜ 来源未进 top-5 {len(no_doc)}")


if __name__ == "__main__":
    main()
