"""只读抽查：对「前 60 块内找不到」的 12 条，扫描该文档**全部**命中块，求含引文块的真实排名。

用于区分两种成因：
  (a) 排名问题 —— 该块在候选池内，只是名次很低（如 65/148）；
  (b) 召回问题 —— 该块根本不在 OR 词元候选池里（索引/切块/词元不含问题）。
只读 PG。
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

TARGETS = [
    ("company-004", "e2"), ("company-004", "a-2"), ("company-004", "a-3"),
    ("company-005", "e2"), ("company-005", "e3"),
    ("company-008", "a-2"), ("company-008", "a-3"), ("company-008", "a-5"),
    ("industry-008", "a-2"),
    ("macro-002", "e4"), ("macro-003", "a-2"), ("macro-003", "a-4"),
]


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
    alias_to_sha = {alias: sha for sha, alias in alias_of.items()}
    rows = {
        (r["query_id"], r["target_id"]): r
        for r in json.loads((HERE / "diagnostics.json").read_text())
    }

    with psycopg.connect(dsn, autocommit=True) as conn:
        for qid, tid in TARGETS:
            row = rows[(qid, tid)]
            question = questions[qid]
            lexemes = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(question.question),),
            ).fetchone()[0]
            query = " OR ".join('"' + term.replace('"', " ") + '"' for term in lexemes)
            hits = search_chunks(dsn, query, limit=2000)
            sha = alias_to_sha[row["source_id"]]
            doc_hits = [h for h in hits if h.source_id == sha]
            texts: list[str] = []
            for hit in doc_hits:
                got = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
                texts.append(norm(got.text))
            quote = norm(row["quote"])
            found = next((i for i, t in enumerate(texts, start=1) if quote in t), None)
            head, tail = quote[:15], quote[-15:]
            head_rank = next((i for i, t in enumerate(texts, start=1) if head in t), None)
            tail_rank = next((i for i, t in enumerate(texts, start=1) if tail in t), None)
            if found:
                verdict = f"在池内，排名={found}"
            elif head_rank and tail_rank and head_rank != tail_rank:
                verdict = (f"**引文跨块**：首段在第{head_rank}块、尾段在第{tail_rank}块"
                           f"（单块永远装不下）")
            elif head_rank and tail_rank and head_rank == tail_rank:
                verdict = f"首尾段同在第{head_rank}块但整句不连续（块内含换行/重组）"
            elif head_rank or tail_rank:
                verdict = f"只有一半在池内（首{head_rank}/尾{tail_rank}）"
            else:
                verdict = "首尾段在候选池内都找不到（块未被 OR 词元召回）"
            print(f"{qid} {tid}: 引文去空白长度={len(quote)} 文档命中块={len(doc_hits)}  {verdict}")


if __name__ == "__main__":
    main()
