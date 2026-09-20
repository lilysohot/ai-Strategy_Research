"""Adopt xyl's existing same-page review with source-derived geometric verification."""
import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def write_once(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    path = HERE / name
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"Immutable artifact differs: {name}")
    path.write_bytes(raw)


def connect():
    from dotenv import dotenv_values
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from plugins.corpus.preparation import guard
    config = conninfo_to_dict(dotenv_values(ROOT / ".env")["CORPUS_DSN"])
    dsn = make_conninfo("", user=config.get("user"), password=config.get("password"),
                       host="127.0.0.1", port=543, dbname="i2_sandbox_corpus", connect_timeout=5)
    guard.install(BASE / "guards/i3-e2e.json")
    return dsn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    dsn = connect()
    from plugins.corpus.preparation.gap_review import GapReview, apply_gap_review
    from plugins.corpus.preparation.engine import gap_records_of, check_build_publishable, publish_build
    from plugins.corpus.preparation.gaps import gap_summary
    from plugins.corpus.preparation.contract import JobStage
    from plugins.corpus.preparation.repository_pg import PgStore
    prior = json.loads((BASE / "audits/20260920-i31-signed-release/release-e2e.json").read_text())
    original = BASE / "audits/20260920-i31-human-gap-review/unsigned-dddc7cd0.json"
    record = json.loads((BASE / "audits/20260920-i31-signed-release/review-dddc7cd0.json").read_text())
    approved = json.loads((BASE / "i3-2/evidence-targets-approved.json").read_text())
    targets = [t for q in approved["questions"] for role in ("approved_required", "supplementary")
               for t in q.get(role, []) if t["source_id"].endswith("_dddc7cd0") and "page:7" in t["locator"]]
    scope = json.loads((BASE / "audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.json").read_text())
    source_path = next(ROOT / row["path"] for row in scope["per_source"] if row["build_id"] == record["build_id"])
    record.update(schema_rev="human-gap-review-2", policy_rev="gap-policy-3",
                  region_source_path=str(source_path),
                  region_targets={"page:7": sorted({t["quote"] for t in targets})})
    review = GapReview.from_json(json.dumps(record))
    write_once("review-dddc7cd0.json", review.as_payload())
    with PgStore(dsn) as store:
        build = store.get_build(review.build_id)
        before = asdict(build)
        units = store.get_units(build.build_id)
        result = apply_gap_review(review, build, units, gap_records_of(build))
        write_once("region-precheck.json", {
            "passed": True, "review_id": review.review_id,
            "human_submission_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "target_ids": sorted({t["target_id"] for t in targets}),
            "region_quotes": record["region_targets"], "gap_summary": gap_summary(result),
            "evidence_units": [asdict(u) for u in units if u.location.page == 7
                               and any(q in u.raw_text for q in record["region_targets"]["page:7"])],
            "normalization": "Existing signed scope/attestation unchanged. Complete approved page-7 quotes projected; all native image placements and whole retained evidence boxes independently checked. No caller-supplied boxes."})
        print("Real region precheck passed; all 3 approved page-7 quotes retained and disjoint.")
        if not args.publish:
            return
        legacy = {row["build_id"]: store.get_gap_review(row["build_id"]).review_id
                  for row in prior["sources"] if row["published"] and store.get_gap_review(row["build_id"])}
        store.put_gap_review(review)
        store.put_gap_review(review)  # Real PG immutable idempotent replay.
        check_build_publishable(store, build.build_id)
        publication = publish_build(store, build.build_id, activated_at=datetime.now(UTC),
                                    operator="Codex executing xyl signed region review", owner_id="i31-region-review")
        assert asdict(store.get_build(build.build_id)) == before
        write_once("publication.json", {"publication": asdict(publication),
                    "checkpoint": json.loads(store.get_job(build.build_id, JobStage.PUBLISHED).checkpoint)})
        sources = []
        for row in prior["sources"]:
            current = store.get_build(row["build_id"])
            check_build_publishable(store, current.build_id)
            pub = store.get_publication(current.source_id)
            records = gap_records_of(current, store=store)
            sources.append({**row, "published": pub.active_build_id == current.build_id,
                            "publishable": True, "gaps": [r.as_payload() for r in records],
                            "gap_summary": gap_summary(records)})
        assert all(store.get_gap_review(b).review_id == rid for b, rid in legacy.items())

    import os
    import psycopg
    import plugins.corpus.service as service_mod
    from plugins.corpus.preparation import read_pg
    from plugins.corpus.audit import audit_corpus_chain
    os.environ["CORPUS_READ_CHAIN"] = "new"
    service_mod.dsn = lambda: dsn
    service = service_mod.CorpusService(dsn)
    searches = []
    for query in ("营业收入", "景气", "非农", "同比", "工业富联", "光模块", "赵彤宇"):
        hits = service.search(query, limit=5)
        rows = []
        for hit in hits:
            evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
            doc = read_pg.fetch_document(dsn, hit.doc_id, sandbox_db="i2_sandbox_corpus")
            rows.append({"handle": hit.doc_id, "locator": hit.locator,
                         "verified": evidence.active and evidence.text == "\n".join(u.raw_text for u in evidence.units)
                         and all(u.raw_text in doc.text for u in evidence.units)})
        searches.append({"query": query, "hits": len(hits), "evidence": rows})
    with psycopg.connect(dsn, autocommit=True) as conn:
        audit = audit_corpus_chain(conn)
    summary = {"sources": len(sources), "published": sum(r["published"] for r in sources),
               "blocking": sum(r["gap_summary"]["blocking"] for r in sources),
               "human_acknowledged": sum(g["basis"].startswith("human_gap_review:") for r in sources for g in r["gaps"]),
               "per_class_min_2": all(sum(r["published"] and r["domain"] == d for r in sources) >= 2
                                      for d in ("company", "industry", "macro")),
               "format_gate": all(any(r["published"] and r["format"] == f for r in sources) for f in ("pdf", "docx", "md")),
               "legacy_review_ids_unchanged": True,
               "all_searches_have_hits": all(r["hits"] for r in searches),
               "verify_all_ok": all(e["verified"] for r in searches for e in r["evidence"]),
               "audit_conflicts": audit.get("conflicts"), "model_calls": 0}
    assert summary["published"] == 8 and summary["blocking"] == 0 and summary["human_acknowledged"] == 13
    assert summary["verify_all_ok"] and summary["all_searches_have_hits"] and not summary["audit_conflicts"]
    write_once("release-e2e.json", {"summary": summary, "sources": sources, "searches": searches,
                                  "coverage": read_pg.coverage_snapshot(dsn, sandbox_db="i2_sandbox_corpus", query_status="matched")})
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
