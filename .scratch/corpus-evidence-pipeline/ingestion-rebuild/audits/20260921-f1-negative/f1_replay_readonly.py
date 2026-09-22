"""F1 负例 6→0 只读重放演示：**不写任何文件**（无 write-once 产物），只读 PG，0 model calls。

用法（仓库根）：

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260921-f1-negative/f1_replay_readonly.py

对 6 条 no-answer 题（company/industry/macro-009/-010）在同一份冻结金标上同时跑两条口径：

- A｜i42 基线：问题**全部词元 OR** 检索 → ``group_hits`` top-5 源 × 8 块（perdoc）
- B｜F1      ：``negative_query.tighten_no_answer_query``（内容词元 AND）+ ``is_relevant_candidate`` 拒检谓词

两侧各自构造 ``QueryObservation`` 并交给 ``plugins.corpus.scoring.score`` 评分，直接对比
``ScoreReport.false_positives`` / ``fabricated_citations``。这复现的是 §14.5 判定门 à la 验收 1/3。

与 ``f1_backtest.py`` 的区别：后者写 write-once 产物（不可重复执行），本脚本只打印，可反复跑。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  reuse group_hits（与 i42/f1 回测同口径）

from plugins.corpus.preparation.chunk import normalize_search_text  # noqa: E402
from plugins.corpus.preparation.negative_query import (  # noqa: E402
    content_lexemes,
    is_relevant_candidate,
    tighten_no_answer_query,
)
from plugins.corpus.preparation.read_pg import (  # noqa: E402
    build_handle,
    chunk_locator,
    fetch_verbatim,
)
from plugins.corpus.preparation.search_pg import _check_target, search_chunks  # noqa: E402
from plugins.corpus.scoring import (  # noqa: E402
    AnswerExistence,
    FetchedEvidence,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
    ScoringPolicy,
    score,
)

SANDBOX = "i2_sandbox_corpus"
TOP_K = 5
BASE_PER_DOC = 8
LIMIT = 2000


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    import psycopg

    records = [
        json.loads(line)
        for line in (INGEST / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()
        if line.strip()
    ]
    negative = [r for r in records if r.get("answer_existence") == AnswerExistence.NO_ANSWER.value]
    if len(negative) != 6:
        raise RuntimeError(f"expected 6 no-answer questions, got {len(negative)}")

    cache: dict = {}

    def fetch(hit):
        key = (hit.build_id, hit.chunk_id)
        if key not in cache:
            cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
        return cache[key]

    def observation_for(query_id: str, grouped) -> QueryObservation:
        """按页聚合带外汇到 RetrievedDocument（与 calibrate.observations_for 语义一致）。"""
        documents = []
        for source_id, hits in grouped.items():
            pages: dict = {}
            build_id = hits[0].build_id
            for hit in hits:
                for unit in fetch(hit).units:
                    pages.setdefault(unit.page, []).append(unit.raw_text)
            evidence = tuple(
                FetchedEvidence(
                    "\n".join(texts),
                    locator=(f"page:{page}",) if page is not None else (),
                    verified=True,
                )
                for page, texts in pages.items()
            )
            documents.append(RetrievedDocument(source_id=source_id, build_id=build_id,
                                               evidence=evidence))
        outcome = ObservationOutcome.NO_MATCH if not documents else ObservationOutcome.OK
        return QueryObservation(query_id=query_id, outcome=outcome, documents=tuple(documents))

    rows = []
    observations_a: list[QueryObservation] = []
    observations_b: list[QueryObservation] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        for record in negative:
            qid = record["query_id"]
            question = record["question"]
            lexemes = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(question),),
            ).fetchone()[0]

            # A｜i42 基线：全部词元 OR
            or_query = " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)
            hits_or = search_chunks(dsn, or_query, limit=LIMIT)
            grouped_or = calibrate.group_hits(hits_or, TOP_K, BASE_PER_DOC)

            # B｜F1：内容词元 AND + 拒检谓词
            tight = tighten_no_answer_query(lexemes or ())
            hits_tight = search_chunks(dsn, tight, limit=LIMIT) if tight else ()
            kept = [
                h for h in hits_tight
                if any(is_relevant_candidate(u.raw_text, lexemes or ()) for u in fetch(h).units)
            ] if content_lexemes(lexemes or ()) else ()
            grouped_tight = calibrate.group_hits(kept, TOP_K, BASE_PER_DOC)

            observations_a.append(observation_for(qid, grouped_or))
            observations_b.append(observation_for(qid, grouped_tight))
            rows.append({
                "query_id": qid,
                "or_chunk_hits": len(hits_or),
                "or_sources": len({h.source_id for h in hits_or}),
                "or_documents": len(grouped_or),
                "tight_tokens": len(content_lexemes(lexemes or ())),
                "tight_chunk_hits": len(hits_tight),
                "tight_sources": len({h.source_id for h in hits_tight}),
                "tight_documents": len(grouped_tight),
            })

    from plugins.corpus.scoring import gold_from_records

    questions = gold_from_records(negative)
    policy = ScoringPolicy()
    report_a = score(questions, observations_a, policy)
    report_b = score(questions, observations_b, policy)

    print("=" * 96)
    print("F1 负例 6→0 只读重放（corpus=index-4-zhcfg-2，scorer=工作树空白规约，0 model_calls）")
    print("=" * 96)
    header = f"{'query_id':<14}{'OR命中块':>9}{'OR命中源':>9}{'A文档数':>8}{'AND词元':>8}" \
             f"{'AND命中块':>10}{'AND源':>7}{'B文档数':>8}{'FP A→B':>9}"
    print(header)
    print("-" * 96)
    for row in rows:
        qid = row["query_id"]
        fp_a = report_a.question(qid).false_positive
        fp_b = report_b.question(qid).false_positive
        print(f"{qid:<14}{row['or_chunk_hits']:>9}{row['or_sources']:>9}{row['or_documents']:>8}"
              f"{row['tight_tokens']:>8}{row['tight_chunk_hits']:>10}{row['tight_sources']:>7}"
              f"{row['tight_documents']:>8}{('Y→N' if fp_a and not fp_b else str(fp_a)):>9}")
    print("-" * 96)
    print(f"A｜i42 基线  false_positives={len(report_a.false_positives)} "
          f"fabricated_citations={len(report_a.fabricated_citations)}")
    print(f"B｜F1        false_positives={len(report_b.false_positives)} "
          f"fabricated_citations={len(report_b.fabricated_citations)}")
    print(f"policy.max_false_positives={policy.max_false_positives} "
          f"max_fabricated_citations={policy.max_fabricated_citations}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
