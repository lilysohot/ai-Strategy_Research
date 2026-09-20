"""Bounded, zero-model development calibration against the frozen 30-question gold."""
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
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name, value):
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {path.name}")
    path.write_bytes(raw)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def group_hits(hits, top_k, per_document):
    """First occurrence follows maximum chunk score; never duplicate a source rank."""
    grouped = {}
    for hit in hits:
        if hit.source_id not in grouped:
            if len(grouped) >= top_k:
                continue
            grouped[hit.source_id] = []
        selected = grouped[hit.source_id]
        if selected and hit.build_id != selected[0].build_id:
            raise ValueError("multiple active builds for one source")
        if len(selected) < per_document:
            selected.append(hit)
    return grouped


def observations_for(query_id, grouped, fetch, aliases):
    """No gold targets supplied: only actual matching chunks may supply evidence."""
    from plugins.corpus.scoring import FetchedEvidence, RetrievedDocument, QueryObservation, ObservationOutcome
    documents = []
    for source_id, hits in grouped.items():
        evidences = []
        for hit in hits:
            result = fetch(hit)
            if result.source_id != source_id or result.build_id != hit.build_id or not result.active:
                raise ValueError("fetch identity/active version mismatch")
            if result.text != "\n".join(u.raw_text for u in result.units):
                raise ValueError("fetch text differs from authoritative units")
            # Pages are obtained from actual units, never copied from expected locators.
            pages = {}
            for unit in result.units:
                pages.setdefault(unit.page, []).append(unit.raw_text)
            for page, texts in pages.items():
                evidences.append(FetchedEvidence("\n".join(texts),
                    locator=(f"page:{page}",) if page is not None else (), verified=True))
        documents.append(RetrievedDocument(aliases.get(source_id, source_id), tuple(evidences), hits[0].build_id))
    return QueryObservation(query_id, ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH,
                            tuple(documents))


def prepare():
    initial_path = BASE / "audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.json"
    initial = json.loads(initial_path.read_text())
    files = [initial_path, BASE / "i3-2/scoring-input-manifest.json", BASE / "i3-2/query-gold-scoring-v1.jsonl",
             BASE / "i3-2/evidence-targets-approved.json", BASE / "i3s2_scoring_input.py",
             ROOT / "plugins/corpus/scoring.py", ROOT / "plugins/corpus/preparation/search_pg.py",
             ROOT / "plugins/corpus/preparation/read_pg.py", ROOT / "plugins/corpus/preparation/chunk.py",
             BASE / "guards/i3-e2e.json", BASE / "freezes/i0c-r38.json", HERE / "calibrate.py",
             HERE / "test_collector.py"]
    plan = {"phase": "I3-3 development calibration", "parent": "i0c-r38",
            "policy": initial["components"]["policy"]["values"],
            "variants": ["baseline_literal_websearch", "candidate_question_lexemes_or"],
            "max_runs": 2, "max_chunk_candidates": 2000, "max_chunks_per_top_document": 8,
            "domain_filter": None, "date_filter": None,
            "ranking": "first occurrence of source in native score-desc chunk order (max chunk score)",
            "candidate_rule": "native zhcfg to_tsvector lexemes from question only, joined by OR; no gold facts or query-specific rules",
            "evidence": "fetch only retrieved chunks of top-5 documents, first 8 per document; exact raw text and native page coordinates",
            "stop": "Run each variant once. Stop on guard/integrity/scope failure, cap saturation, or completion of two reports. No tuning after scores in this revision.",
            "prohibitions": ["no models", "no holdout", "no source/gold/threshold changes", "no production DB", "no production retrieval change"],
            "binding": {str(p.relative_to(ROOT)): digest(p) for p in files}}
    plan["pre_run_correction"] = "Import-only fix document_handle -> build_handle; first attempt stopped before opening PG or querying. Original script and plan retained; same two variants and bounds."
    write_once("calibration-plan-v2.json", plan)
    print("Fixed two-run plan saved before retrieval; no outputs consulted.")


def main():
    if "--prepare" in sys.argv:
        prepare()
        return
    plan = json.loads((HERE / "calibration-plan-v2.json").read_text())
    for rel, sha in plan["binding"].items():
        if digest(ROOT / rel) != sha:
            raise RuntimeError(f"Pre-run binding drift: {rel}")
    if (HERE / "calibration-summary.json").exists():
        raise RuntimeError("This bounded experiment is already complete")
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()
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
    release_result = json.loads((BASE / "audits/20260920-i31-region-review/release-e2e.json").read_text())
    sources = {r["source_id"]: r["build_id"] for r in release_result["sources"]}
    aliases = {}
    expected_aliases = {s for q in questions for s in q.relevant_sources}
    expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
    for alias in expected_aliases:
        matches = [source for source in sources if source.startswith(alias.rsplit("_", 1)[-1])]
        if len(matches) != 1:
            raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
        if matches[0] in aliases and aliases[matches[0]] != alias:
            raise RuntimeError("Multiple gold aliases for one source")
        aliases[matches[0]] = alias
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        def snapshot():
            return dict(conn.execute("SELECT source_id, active_build_id FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL").fetchall())
        if snapshot() != sources:
            raise RuntimeError("Active corpus differs from approved eight builds")
        write_once("source-identity-map.json", {"aliases": aliases, "active_builds": sources})
        cache = {}
        receipts = {}
        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]
        summaries = []
        for variant in plan["variants"]:
            observations, traces = [], []
            for question in questions:
                query = question.question
                if variant == "candidate_question_lexemes_or":
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
                grouped = group_hits(hits, policy.top_k, plan["max_chunks_per_top_document"])
                observation = observations_for(question.query_id, grouped, fetch, aliases)
                observations.append(observation)
                traces.append({"query_id": question.query_id, "input_question": question.question,
                               "executed_query": query, "native_tsquery": tsquery, "chunk_hits": len(hits),
                               "selected": {s: [asdict(h) for h in hlist] for s, hlist in grouped.items()}})
            if snapshot() != sources:
                raise RuntimeError("Active publication changed during calibration")
            report = score(questions, observations, policy)
            write_once(variant + "-observations.json", [asdict(o) for o in observations])
            write_once(variant + "-trace.json", traces)
            write_once(variant + "-score.json", asdict(report))
            (HERE / (variant + "-score.md")).write_text(format_report(report) + "\n")
            summary = {"variant": variant, "passed": report.passed,
                       "per_class": [{"domain": c.domain, "doc_recall": str(c.doc_recall.rate),
                                      "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
                                      "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"} for c in report.classes],
                       "no_match": sum(not t["chunk_hits"] for t in traces),
                       "false_positives": report.false_positives, "critical_failures": report.critical_failures,
                       "failures": dict(Counter(f.split(":")[0] for q in report.questions for f in q.failures))}
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        write_once("fetch-receipts.json", receipts)
        write_once("calibration-summary.json", {"runs": summaries, "questions": len(questions),
                   "scoring_input_unchanged": digest(loader.OUT_JSONL) == plan["binding"][str(loader.OUT_JSONL.relative_to(ROOT))],
                   "publication_unchanged": snapshot() == sources, "model_calls": 0,
                   "stop_reason": "predeclared_two_runs_complete", "production_query_changed": False,
                   "note": "Development calibration only; no answer-generation semantics or M6 claim. Native page locators only; no inferred row/column labels."})


if __name__ == "__main__":
    main()
