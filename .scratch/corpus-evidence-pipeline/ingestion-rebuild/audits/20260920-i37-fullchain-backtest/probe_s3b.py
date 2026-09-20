"""只读：原题查询下，含引文的块在目标文档的命中排序位置（决定 S3 机制）。
对代表性案例，取原题 OR 查询在该文档上的 top-N 命中，fetch 文本判断引文在哪个位置。
"""
from __future__ import annotations
import importlib.util, json, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE / "audits/20260920-i31-region-review"))
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
dsn = release.connect()
WS = re.compile(r"\s+")
def norm(s): return WS.sub("", s)
from plugins.corpus.preparation.search_pg import search_chunks
from plugins.corpus.preparation.chunk import normalize_search_text
from plugins.corpus.preparation.read_pg import fetch_verbatim, build_handle, chunk_locator
import psycopg

diag = json.load(open(HERE / "diagnostics.json"))
ident = json.load(open(HERE / "source-identity-map.json"))
alias_to_src = {a: s for s, a in ident["aliases"].items()}
qs = json.load(open(HERE / "candidate_question_lexemes_or-trace.json"))
q2 = {t["query_id"]: t for t in qs}
CASES = ["company-004:e2", "industry-008:a-3", "macro-002:e4"]

with psycopg.connect(dsn, autocommit=True) as conn:
    for case in CASES:
        qid, tid = case.split(":")
        r = next(x for x in diag if x["query_id"]==qid and x["target_id"]==tid)
        src = alias_to_src.get(r["source_id"], r["source_id"])
        t = q2[qid]
        hits = [h for h in search_chunks(dsn, t["executed_query"], limit=2000) if h.source_id == src]
        print(f"== {qid} {tid}: doc hits={len(hits)} quote='{norm(r['quote'])[:30]}'")
        found_at = None
        for i, h in enumerate(hits):
            if i >= 60: break
            try:
                fv = fetch_verbatim(dsn, build_handle(h.build_id), chunk_locator(h.chunk_id))
            except Exception:
                continue
            if norm(r["quote"]) in norm(fv.text):
                found_at = i
                print(f"   FOUND at rank {i} (score={h.score:.4f}) chunk={h.chunk_id[-24:]}")
                break
        if found_at is None:
            print("   NOT in top-60 (需引文词元定位)")
