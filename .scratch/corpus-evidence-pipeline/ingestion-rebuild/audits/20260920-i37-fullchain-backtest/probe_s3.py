"""只读核查：21 条 kept_page_not_selected 引文所在块是否在检索索引内（无金标泄漏的排序修复可行性）。
若块在索引内但分数排不进 top-8 → 纯选择问题；若块不在索引内 → 需要引文词元定位。
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
import psycopg

diag = json.load(open(HERE / "diagnostics.json"))
ident = json.load(open(HERE / "source-identity-map.json"))
alias_to_src = {a: s for s, a in ident["aliases"].items()}
targets = [r for r in diag if r["bucket"] == "kept_page_not_selected"]

with psycopg.connect(dsn, autocommit=True) as conn:
    for r in targets:
        qid, tid = r["query_id"], r["target_id"]
        src = alias_to_src.get(r["source_id"], r["source_id"])
        quote = r["quote"]
        lex = " OR ".join('"' + t.replace('"', " ") + '"' for t in
                          conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                       (normalize_search_text(quote),)).fetchone()[0])
        # 全库检索引文词元，看命中块是否在目标文档上
        hits = search_chunks(dsn, lex, limit=2000)
        doc_hits = [h for h in hits if h.source_id == src]
        # 检查是否存在含该引文的块（内容级确认靠后续 fetch，这里只看检索层面有无该文档块被词元召回）
        print(f"{qid} {tid}: quote_lex_hits_on_src={len(doc_hits)} question_or_hits_total={len(hits)}")
