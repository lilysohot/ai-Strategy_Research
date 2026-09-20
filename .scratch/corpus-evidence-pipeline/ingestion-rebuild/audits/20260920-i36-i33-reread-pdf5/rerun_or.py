"""I3-3 单一回归复核：在 reader-pdf-5 重摄入的沙箱 active corpus 上重跑 retrieval+scoring。

背景：
- r39 冻结的是 reader-pdf-2 的 active corpus；i35（20260920-i35-reingest-pdf5）在 teardown
  重建的沙箱上以 reader-pdf-5 全量重摄入并 publish 了 8 份（其中 4 份经人工 gap-review 重签后
  publish）。i35-pg-kept-forensics 证明 kept 引文在 reader-pdf-5 文本里存在，但**尚未真正
  重跑检索+评分**。本脚本补上这一步。
- 只跑 OR variant（baseline_literal_websearch 已证在 reader-pdf-2 下 0 命中，无意义）。
- 用冻结 scorer（plugins/corpus/scoring.py）与冻结评分输入（i3-2/query-gold-scoring-v1.jsonl
  经 i3s2_scoring_input manifest 校验）。
- 不改金标、不改 scorer、不做参数调参 & 严格 bounds 与中止条件（对齐 calibrate.py）。
- 读取 **实时** active builds（corpus_publications），不依赖 stale release-e2e.json；仅对照
  gold alias 唯一解析到 live 来源。

本轮为限定回归：metr三指标 per_class + 负例误报 + 与 r39 OR variant 对比。
"""
from collections import Counter
from dataclasses import asdict
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I33 = BASE / "audits/20260920-i33-calibration"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # 复用 group_hits / observations_for（与 I3-3 同一 grouping/fetch 语义）  # noqa: E402

VARIANT = "candidate_question_lexemes_or"  # only variant for this single regression


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name, value):
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    plan = json.loads((I33 / "calibration-plan-v2.json").read_text())
    # 冻结资产绑定：评分输入派生态 + scorer + 检索读侧必须与 r39 批准的字节一致。
    bound = {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json": plan["binding"][".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json"],
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl": plan["binding"][".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"],
        "plugins/corpus/scoring.py": plan["binding"]["plugins/corpus/scoring.py"],
        "plugins/corpus/preparation/search_pg.py": plan["binding"]["plugins/corpus/preparation/search_pg.py"],
        "plugins/corpus/preparation/read_pg.py": plan["binding"]["plugins/corpus/preparation/read_pg.py"],
        "plugins/corpus/preparation/chunk.py": plan["binding"]["plugins/corpus/preparation/chunk.py"],
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json": plan["binding"][".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json"],
    }
    for rel, sha in bound.items():
        if digest(ROOT / rel) != sha:
            raise RuntimeError(f"Frozen asset drift vs r39: {rel}")

    dsn = release_connect()
    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(BASE / "i3s2_apply_decisions.py", "i33_approved_input")
    errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
        json.loads(loader.PROJECTION.read_text()), loader.load_jsonl(loader.SOURCE_GOLD),
        json.loads(loader.MANIFEST.read_text()), applier)
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")

    from plugins.corpus.scoring import gold_from_records, ScoringPolicy, score, format_report
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import fetch_verbatim, build_handle, chunk_locator
    import psycopg

    questions = gold_from_records(records)
    config = dict(plan["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")

        def snapshot():
            return dict(conn.execute(
                "SELECT source_id, active_build_id FROM corpus.corpus_publications "
                "WHERE active_build_id IS NOT NULL").fetchall())

        sources = snapshot()
        if len(sources) != 8:
            raise RuntimeError(f"Active corpus has {len(sources)} sources (expected 8: i35 reader-pdf-5 dev lane)")

        # alias 解析：与 calibrate.main() 完全一致（仅来源变为 live active builds）。
        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely in live active corpus: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        write_once("source-identity-map.json", {"aliases": aliases, "active_builds": sources})

        cache = {}
        receipts = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        traces = []
        observations = []
        for question in questions:
            query = question.question
            lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                   (normalize_search_text(query),)).fetchone()[0]
            if not lexemes:
                raise RuntimeError("Question tokenization produced no terms")
            query = " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)
            tsquery = conn.execute("SELECT websearch_to_tsquery('zhcfg', %s)::text",
                                   (normalize_search_text(query),)).fetchone()[0]
            hits = search_chunks(dsn, query, limit=plan["max_chunk_candidates"])
            if len(hits) >= plan["max_chunk_candidates"]:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
            grouped = calibrate.group_hits(hits, policy.top_k, plan["max_chunks_per_top_document"])
            observation = calibrate.observations_for(question.query_id, grouped, fetch, aliases)
            observations.append(observation)
            traces.append({"query_id": question.query_id, "input_question": question.question,
                           "executed_query": query, "native_tsquery": tsquery, "chunk_hits": len(hits),
                           "selected": {s: [asdict(h) for h in hlist] for s, hlist in grouped.items()}})
            if snapshot() != sources:
                raise RuntimeError("Active publication changed during re-run")

        if snapshot() != sources:
            raise RuntimeError("Active publication changed during re-run")
        report = score(questions, observations, policy)
        write_once(VARIANT + "-observations.json", [asdict(o) for o in observations])
        write_once(VARIANT + "-trace.json", traces)
        write_once(VARIANT + "-score.json", asdict(report))
        (HERE / (VARIANT + "-score.md")).write_text(format_report(report) + "\n")
        write_once("fetch-receipts.json", receipts)

        summary = {
            "variant": VARIANT,
            "corpus": "reader-pdf-5 reingest + gap-review republish (i35)",
            "passed": report.passed,
            "per_class": [{"domain": c.domain, "doc_recall": str(c.doc_recall.rate),
                           "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
                           "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"}
                          for c in report.classes],
            "no_match": sum(not t["chunk_hits"] for t in traces),
            "false_positives": report.false_positives,
            "fabricated_citations": report.fabricated_citations,
            "critical_failures": report.critical_failures,
            "failures": dict(Counter(f.split(":")[0] for q in report.questions for f in q.failures)),
            "model_calls": 0,
            "questions": len(questions),
        }
        write_once("rerun-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


def release_connect():
    """与 calibrate.py 同口径：读 .env CORPUS_DSN，连沙箱 i2_sandbox_corpus，装 i3-e2e 守卫。"""
    decrease = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    return decrease.connect()


if __name__ == "__main__":
    main()