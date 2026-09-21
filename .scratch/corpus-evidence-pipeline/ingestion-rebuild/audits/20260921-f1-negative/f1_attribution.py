"""F1 负例判定层拒检门：第一步「机读归因」探针（只读 PG，0 model calls）。

对 6 条 no-answer 题（company/industry/macro-009/-010），运行与带产品回测
完全相同的 OR 词元检索路径（search_chunks limit=2000），固化「token → 命中块」
归因表：对每题每个候选中块，列出该块命中（出现）了哪些**非停用**问题词元，
以及命中块数 / 候选文档数。产物 write-once 写入本目录：
  f1-attribution.json  机读归因表
  f1-attribution.md    人类可读 FP 归因表（验收 2：每题固化 token→命中块）

这仅是归因探针，**不做任何判定改动**。阈值设计在阅读本表后单独落地。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
I42 = AUDITS / "20260920-i42-topic-b-reingest"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

SANDBOX = "i2_sandbox_corpus"

# 问题里的纯功能/套话词元 —— 它们命中大量无关文档，构不成实质答案信号。
_FUNCTION_WORDS = {
    "这", "六", "份", "开发", "材料", "能否", "能", "否", "给出", "给", "出", "是", "否",
    "是否", "的", "了", "是否披露", "披露", "份开发", "材料", "这六份",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import (fetch_verbatim, build_handle, chunk_locator)
    from plugins.corpus.scoring import AnswerExistence

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    query_gold = INGEST / "i3-2/query-gold-scoring-v1.jsonl"
    records = [json.loads(ln) for ln in query_gold.read_text().splitlines() if ln.strip()]
    neg = [q for q in records
           if q.get("answer_existence") == AnswerExistence.NO_ANSWER.value]
    if len(neg) != 6:
        raise RuntimeError(f"Expected 6 no-answer questions, got {len(neg)}")
    with ReleaseConn(dsn) as conn:
        _check_target(conn.conn, SANDBOX)
        cases = []
        for q in neg:
            qid, question = q["query_id"], q["question"]
            lexemes = conn.conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(question),)).fetchone()[0]
            content = [t for t in lexemes if not _is_function(t)]
            or_query = " OR ".join('"' + t.replace('"', ' ') + '"' for t in lexemes)
            hits = search_chunks(dsn, or_query, limit=2000)
            per_block = []
            for hit in hits:
                unit_refs = {hit.build_id: set(hit.unit_refs)}
                raw_by = {}
                with conn.conn.cursor() as cur:
                    cur.execute(
                        "SELECT unit_id, raw_text, content_hash FROM corpus.corpus_units "
                        "WHERE build_id=%s AND unit_id = ANY(%s)",
                        (hit.build_id, list(hit.unit_refs)))
                    for uid, raw, chash in cur.fetchall():
                        if hashlib.sha256(str(raw or "").encode()).hexdigest() != str(chash or ""):
                            raise RuntimeError(f"内容哈希不符 {uid}")
                        raw_by[uid] = str(raw or "")
                block_text = "\n".join(raw_by[u] for u in hit.unit_refs)
                matched = [t for t in content if _norm(t) in _norm(block_text)]
                # 单元级共现：unit 内命中 ≥2 个不同 content 词元的"密块"才算强信号。
                # （块级子串会把隔开的不同单元误并为一次共现；单元级是"命中块/句"粒度。）
                dense_units: list[dict] = []
                for u in hit.unit_refs:
                    ut = raw_by[u]
                    um = [t for t in content if _norm(t) in _norm(ut)]
                    if len(um) >= 2:
                        dense_units.append({"unit": str(u)[:10],
                                            "tokens": um,
                                            "preview": ut[:40]})
                per_block.append({
                    "chunk_id": str(hit.chunk_id),
                    "source_id": hit.source_id,
                    "score": round(hit.score, 6),
                    "matched_tokens": matched,
                    "n_matched": len(matched),
                    "n_dense_units": len(dense_units),
                    "dense_units": dense_units[:3],
                })
            cases.append({
                "query_id": qid,
                "question": question,
                "question_tokens": lexemes,
                "content_tokens": content,
                "chunk_hits": len(hits),
                "saturated": len(hits) >= 2000,
                "groups": len({b["source_id"] for b in per_block}),
                "blocks": per_block,
            })
    out = {
        "artifact": "f1-attribution",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "kind": "负例机读归因（只读，0 model_calls）",
        "corpus": "index-4-zhcfg-2 active (8 builds)",
        "scorer": "working-tree whitespace-norm (NOT frozen)",
        "note": ("命中判定 = zhcfg 词元在**块文本**内的空白规约子串包含。"
                 "matched_tokens 仅列非停用 content token，用于阈值设计。"),
        "function_words": sorted(_FUNCTION_WORDS),
        "model_calls": 0,
        "cases": cases,
    }
    write_once("f1-attribution.json", out)
    (HERE / "f1-attribution.md").write_text(_render_md(out) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases),
                      "per_query_retrieved_docs": {c["query_id"]: c["groups"] for c in cases},
                      "per_query_chunk_hits": {c["query_id"]: c["chunk_hits"] for c in cases},
                      "max_blocks_with_cross_token": {
                          c["query_id"]: [b["matched_tokens"] for b in c["blocks"]
                                          if b["n_matched"] >= 2] for c in cases}},
                      ensure_ascii=False, indent=2))
    return 0


def _is_function(token: str) -> bool:
    return token in _FUNCTION_WORDS or len(token) == 1


def _norm(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace())


def _render_md(out) -> str:
    lines = ["# F1 负例机读归因表（token → 命中块）", "",
             f"- 生成：{out['generated_at']}；类型：只读归因，0 model calls",
             f"- 语料：{out['corpus']}；检索：问题词元 OR（limit=2000）",
             f"- 停用词元：{' '.join(out['function_words'])}", ""]
    for c in out["cases"]:
        lines += [f"## {c['query_id']}：{c['question']}", "",
                  f"- 词元总数 {len(c['question_tokens'])}；content 词元 "
                  f"{len(c['content_tokens'])}：{' '.join(c['content_tokens'])}",
                  f"- 块命中 {c['chunk_hits']}（{c['saturated'] and '饱和' or '未饱和'}）；"
                  f"源文档数 {c['groups']}", "",
                  "| 块 | 源 | score | 命中 content 词元 | 命中数 | 密块数 |",
                  "|---|---|---:|---|---:|---:|"]
        for b in c["blocks"]:
            dense = "; ".join(f"{d['unit']}({' '.join(d['tokens'])})" for d in b["dense_units"])
            lines.append(f"| {b['chunk_id'][:8]} | {b['source_id'][:16]} | {b['score']} | "
                         f"{' '.join(b['matched_tokens'])} | {b['n_matched']} | "
                         f"{b['n_dense_units']} {dense} |")
        lines.append("")
    return "\n".join(lines)


class ReleaseConn:
    """tiny context wrapper reusing dsn only (read-only)."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = None

    def __enter__(self):
        import psycopg
        self.conn = psycopg.connect(self.dsn, autocommit=True)
        return self

    def __exit__(self, *exc):
        if self.conn is not None:
            self.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())