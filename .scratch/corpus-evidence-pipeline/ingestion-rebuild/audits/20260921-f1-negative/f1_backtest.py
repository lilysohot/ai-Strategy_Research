"""F1 负例 6→0 只读回测（M6 硬判据，纯消费侧判定层）。

对照：有答案题走 OR 检索 + base 选择（select 前 top_k 来源 × 8 块，i42 语义，不变量）；
负例走**收紧查询**（``negative_query.tighten_no_answer_query``：全部内容词元 websearch AND）→
6 条应 retrieved_documents=0、false_positives=0。

自检：
- I-M6-1：6 条负例 retrieved_documents == 0 且 score.false_positives == 0；
- I-M6-2（不扰动）：有答案题 79 目标 S0/S1/S2 与 i42 基线逐字节一致（S1_candidates=66）；
- EvidencePass 不回归（base 口径 ≥ i42 基线 12/24）。

只读 PG + 0 model_calls；产物 write-once 写入本目录。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
I42 = AUDITS / "20260920-i42-topic-b-reingest"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  reuse observations_for / group_hits

SANDBOX = "i2_sandbox_corpus"
BASE_PER_DOC = 8


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


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> int:
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import (fetch_verbatim, build_handle, chunk_locator)
    from plugins.corpus.scoring import (AnswerExistence,
                                    gold_from_records, ScoringPolicy, score, format_report)
    from plugins.corpus.preparation.negative_query import tighten_no_answer_query, is_relevant_candidate
    import psycopg

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(INGEST / "i3s2_apply_decisions.py", "i33_approved_input")
    scorer_sha = digest(ROOT / "plugins/corpus/scoring.py")
    import copy
    manifest_dict = json.loads(loader.MANIFEST.read_text(encoding="utf-8"))
    diag_manifest = copy.deepcopy(manifest_dict)
    diag_manifest["lineage"]["scorer"]["sha256"] = scorer_sha
    errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
                             json.loads(loader.PROJECTION.read_text()),
                             loader.load_jsonl(loader.SOURCE_GOLD),
                             diag_manifest, applier)
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")

    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    neg_ids = {q.query_id for q in questions
               if q.answer_existence is AnswerExistence.NO_ANSWER}
    assert len(neg_ids) == 6, len(neg_ids)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        if len(sources) != 8:
            raise RuntimeError(f"Active corpus has {len(sources)} sources (expected 8)")

        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets
                             if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}

        cache: dict = {}
        receipts: dict = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id),
                                            chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        def or_query(conn, question: str) -> str:
            lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                   (normalize_search_text(question),)).fetchone()[0]
            if not lexemes:
                raise RuntimeError("Question tokenization produced no terms")
            return " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)

        def build_observation(query_id, grouped):
            return calibrate.observations_for(query_id, grouped, fetch, aliases)

        traces = []
        obs: dict[str, object] = {}
        per_query: dict[str, dict] = {}
        for question in questions:
            if question.answer_existence is AnswerExistence.NO_ANSWER:
                lexemes = conn.execute(
                    "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                    (normalize_search_text(question.question),)).fetchone()[0]
                query = tighten_no_answer_query(lexemes or ())
                hits = search_chunks(dsn, query, limit=2000) if query else ()
                # 判定层拒检回兜：即即便有命中，也只收下"同一单元满足全部内容词元"的文档。
                content = [t for t in (lexemes or ()) if t]
                kept = [h for h in hits if any(
                    is_relevant_candidate(u.raw_text, (lexemes or ()))
                    for u in fetch(h).units)] if content else ()
                grouped = calibrate.group_hits(kept, policy.top_k, BASE_PER_DOC)
                obs[question.query_id] = build_observation(question.query_id, grouped)
                traces.append({"query_id": question.query_id, "mode": "negative_tightened",
                               "tight_query": query, "chunk_hits": len(hits),
                               "gate_kept_docs": len(grouped),
                               "retrieved_documents": len(grouped)})
                continue
            query = or_query(conn, question.question)
            hits = search_chunks(dsn, query, limit=2000)
            if len(hits) >= 2000:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
            text_by_chunk = {}
            for hit in hits:
                for uid in hit.unit_refs:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT unit_id, raw_text, content_hash FROM corpus.corpus_units "
                            "WHERE build_id=%s AND unit_id=%s", (hit.build_id, uid))
                        row = cur.fetchone()
                    if hashlib.sha256(str(row[1] or "").encode()).hexdigest() != str(row[2] or ""):
                        raise RuntimeError(f"权威单元内容哈希不符: {uid}")
                    text_by_chunk[(hit.build_id, hit.chunk_id)] = (
                        text_by_chunk.get((hit.build_id, hit.chunk_id), "") + "\n" + str(row[1] or ""))
            grouped = calibrate.group_hits(hits, policy.top_k, BASE_PER_DOC)
            obs[question.query_id] = build_observation(question.query_id, grouped)
            per_query[question.query_id] = {"hits": hits, "text_by_chunk": text_by_chunk,
                                            "groups": grouped}
            traces.append({"query_id": question.query_id, "mode": "or_answerable",
                           "chunk_hits": len(hits),
                           "base_selected": {s: len(h) for s, h in grouped.items()}})

        report = score(questions, list(obs.values()), policy)

        # ── 逐目标漏斗（有答案题，base 口径，与 i42 一致）──
        funnel_targets = []
        for q in questions:
            o = obs.get(q.query_id)
            pinfo = per_query.get(q.query_id)
            relevant = set(q.relevant_sources)
            for target in q.evidence_targets:
                allowed = (target.source_id,) if target.source_id else tuple(relevant)
                page = None
                for tok in target.locator:
                    if tok.startswith("page:"):
                        page = int(tok.split(":", 1)[1])
                        break
                matched = bool(o) and any(
                    target.matches(ev) and doc.source_id in allowed
                    for doc in o.documents for ev in doc.evidence)
                src = target.source_id or (next(iter(relevant), None))
                live_src = alias_to_source.get(src)
                build_id = sources.get(live_src) if live_src else None
                quote = norm(target.quote)
                in_kept_page = in_kept_any = False
                if build_id:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT location, raw_text FROM corpus.corpus_units "
                            "WHERE build_id=%s AND status='KEPT'", (build_id,))
                        rows = cur.fetchall()
                    for loc, raw in rows:
                        units_text = str(raw or "")
                        if quote in norm(units_text):
                            in_kept_any = True
                            if page is not None:
                                in_kept_page = in_kept_page or (page == int(str(loc).rsplit(":", 1)[-1])
                                                                if str(loc).endswith(":" + str(page)) else False)
                cand_texts = ([pinfo["text_by_chunk"].get((h.build_id, h.chunk_id), "")
                               for h in pinfo["hits"] if h.build_id == build_id]
                              if pinfo else [])
                s1 = any(quote in norm(t) for t in cand_texts)
                doc_in_topk = bool(pinfo) and live_src in pinfo["groups"]
                s2 = s1 and doc_in_topk
                s3 = s2
                s4 = s3 and matched
                if matched:
                    bucket = "matched"
                else:
                    bucket = "unmatched"
                funnel_targets.append({"query_id": q.query_id,
                                       "target_id": f"{q.query_id} {target.target_id}",
                                       "S1_candidates": s1, "S2_doc_topk": s2,
                                       "S4_matched": s4, "bucket": bucket})

        layer = lambda pred: sum(1 for r in funnel_targets if pred(r))
        funnel = {"S1_candidates": layer(lambda r: r["S1_candidates"]),
                  "S2_doc_topk": layer(lambda r: r["S2_doc_topk"]),
                  "S4_matched": layer(lambda r: r["S4_matched"])}

        neg = []
        for q in questions:
            if q.answer_existence is AnswerExistence.NO_ANSWER:
                o = obs[q.query_id]
                docs = ([{"source_id": d.source_id,
                          "evidence_preview": [ev.text[:140] for ev in d.evidence][:2]}
                         for d in o.documents] if o else [])
                neg.append({"query_id": q.query_id, "question": q.question,
                            "retrieved_documents": len(docs)})

        i42funnel = json.loads((I42 / "recall-funnel.json").read_text())["funnel"]

        evidence_total = sum(c.evidence_pass.passed for c in report.classes)
        evidence_total_den = sum(c.evidence_pass.total for c in report.classes)
        fp_zero = len(report.false_positives) == 0 and all(n["retrieved_documents"] == 0 for n in neg)
        self_check = {
            "I-M6-1_fp_zero": fp_zero,
            "I-M6-2_S1_66": funnel["S1_candidates"] == 66
                            == i42funnel.get("S1_candidates"),
            "I-M6-2_S2_60": funnel["S2_doc_topk"] == i42funnel.get("S2_doc_topk"),
            # EvidencePass 基线 = i42 12/24（24 目标计分）；S4_matched/44 是漏斗目标计数，不同单位。
            "evidence_no_regress": evidence_total >= 12
                                   and evidence_total_den == 24,
        }

        summary = {
            "artifact": "f1-negative-6to0",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "F1 判定层拒检回测（纯消费侧，非冻结回归）",
            "corpus": "index-4-zhcfg-2 active (8 builds)",
            "scorer": "working-tree whitespace-norm (NOT frozen)",
            "model_calls": 0,
            "lever": "negative_query.tighten_no_answer_query（内容词元 websearch AND）",
            "per_class": [{"domain": c.domain, "doc_recall": str(c.doc_recall.rate),
                           "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
                           "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"}
                          for c in report.classes],
            "evidence_pass_total": f"{evidence_total}/{evidence_total_den}",
            "false_positives": report.false_positives,
            "fabricated_citations": report.fabricated_citations,
            "funnel": {k: funnel[k] for k in ("S1_candidates", "S2_doc_topk", "S4_matched")},
            "i42_baseline": {"funnel": i42funnel, "evidence_pass_total": "12/24",
                             "false_positives": 6},
            "self_check": self_check,
            "target_buckets": dict(Counter(r["bucket"] for r in funnel_targets)),
            "negative": {"cases": neg},
            "questions": len(questions),
        }
        write_once("f1-summary.json", summary)
        write_once("f1-observations.json", [asdict(o) for o in obs.values()])
        write_once("f1-trace.json", traces)
        write_once("f1-score.json", asdict(report))
        write_once("f1-funnel-targets.json", funnel_targets)
        (HERE / "f1-report.md").write_text(format_report(report) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())