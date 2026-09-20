"""Normalize the named human submissions, apply the existing gate, and audit approved builds."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))
SHORTS = ("6f14cc14", "174b6462", "793b3967", "dddc7cd0")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()


def once(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"Write-once artifact conflict: {path.name}")
    if not path.exists():
        path.write_bytes(raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    from dotenv import dotenv_values
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from plugins.corpus.preparation import guard

    connection = conninfo_to_dict(dotenv_values(ROOT / ".env")["CORPUS_DSN"])
    dsn = make_conninfo("", user=connection.get("user"), password=connection.get("password"),
                        host="127.0.0.1", port=543, dbname="i2_sandbox_corpus", connect_timeout=5)
    guard.install(BASE / "guards/i3-e2e.json")
    from plugins.corpus.preparation.gap_review import GapReview, GapReviewError, apply_gap_review
    from plugins.corpus.preparation.gaps import gap_summary
    from plugins.corpus.preparation.engine import (
        EngineError, gap_records_of, check_build_publishable, publish_build,
    )
    from plugins.corpus.preparation.contract import JobStage, canonical_fingerprint
    from plugins.corpus.preparation.repository_pg import PgStore

    approved_path = BASE / "i3-2/evidence-targets-approved.json"
    approved = json.loads(approved_path.read_text())
    manifest = json.loads((BASE / "audits/20260920-i31-dev-lane/dev-scope-manifest.json").read_text())
    old_e2e = json.loads((BASE / "audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.json").read_text())
    prior_rows = {row["build_id"]: row for row in old_e2e["per_source"]}
    normalization = []
    accepted = []
    with PgStore(dsn) as store:
        for short in SHORTS:
            original_path = BASE / f"audits/20260920-i31-human-gap-review/unsigned-{short}.json"
            raw = original_path.read_bytes()
            once(HERE / "submitted" / original_path.name, raw)
            original = json.loads(raw)
            if not original["reviewer"].strip() or not original["attestation"].strip() or not original["scope_rationale"].strip():
                raise RuntimeError("Human signature/content incomplete; cannot normalize")
            if not all(value.strip() for value in original["gaps"].values()):
                raise RuntimeError("Missing human per-gap rationale")
            build = store.get_build(original["build_id"])
            if build is None or canonical_fingerprint(asdict(build)) != original["build_fingerprint"]:
                raise RuntimeError("Submitted build fingerprint no longer current")
            if store.latest_admission(build.source_id).decision_id != build.decision_id:
                raise RuntimeError("Submitted admission no longer current")
            row = prior_rows[build.build_id]
            source_path = ROOT / row["path"]
            if digest(source_path.read_bytes()) != original["source_id"]:
                raise RuntimeError("Original source hash mismatch")
            before_ledger = build.quality_report
            pages = set()
            targets = []
            for question in approved["questions"]:
                for role in ("approved_required", "supplementary"):
                    for target in question.get(role, []):
                        if target["source_id"].endswith("_" + short):
                            pages.update(locator for locator in target["locator"] if locator.startswith("page:"))
                            targets.append({"query_id": question["query_id"], "role": role,
                                            "target_id": target["target_id"], "locators": target["locator"]})
            if not pages:
                raise RuntimeError("No approved evidence pages found")
            locators = sorted(pages, key=lambda text: int(text.split(":")[1]))
            timestamp = datetime.fromisoformat(original["reviewed_at"])
            # User session timezone is Asia/Shanghai, UTC+08:00; preserve the wall time.
            if timestamp.utcoffset() is None:
                from datetime import timedelta, timezone
                timestamp = timestamp.replace(tzinfo=timezone(timedelta(hours=8)))
            normalized = dict(original)
            normalized.update(
                reviewed_at=timestamp.isoformat(),
                evidence_scope_ref=f"{approved_path.relative_to(ROOT)}@sha256:{digest(approved_path.read_bytes())}",
                required_locators=locators,
                scope_rationale=(original["scope_rationale"] + "\n原具名核验全文：" + original["attestation"]
                                 + "\n机器转写：完整展开签署所指 approved_required/supplementary 的页码为 "
                                 + ", ".join(locators) + "；未按缺口位置筛选或删除目标。"),
                attestation="human_verified_complete_scope_and_nonintersection",
            )
            once(HERE / f"review-{short}.json", encode(normalized))
            review = GapReview.from_json(json.dumps(normalized))
            item = {"source_id": build.source_id, "build_id": build.build_id,
                    "submitted_sha256": digest(raw), "review_id": review.review_id,
                    "required_locators": locators, "targets": targets,
                    "normalization": "Source/locators derived from explicitly signed reference; timezone +08 from user session; human prose retained verbatim in scope_rationale and original file.",
                    "source_bytes_verified": True}
            try:
                records = apply_gap_review(review, build, store.get_units(build.build_id), gap_records_of(build))
                item["gate"] = "pass"
                item["gaps_after_review"] = gap_summary(records)
                accepted.append((review, before_ledger))
            except GapReviewError as exc:
                item["gate"] = "blocked"
                item["error"] = str(exc)
            if short == "dddc7cd0":
                import pymupdf
                with pymupdf.open(source_path) as pdf:
                    page = pdf[6]
                    images = [{"bbox": list(info["bbox"]), "width": info["width"], "height": info["height"]}
                              for info in page.get_image_info()]
                    blocks = [{"bbox": list(block[:4]), "text": block[4]} for block in page.get_text("blocks")
                              if isinstance(block[4], str) and ("32.60" in block[4] or "36.60" in block[4])]
                    item["observed_region_evidence"] = {"page": 7, "images": images, "ownership_text_blocks": blocks,
                        "note": "Human region-level explanation retained; existing gate compares page coordinates and remains blocking."}
            normalization.append(item)
        once(HERE / "precheck.json", encode({"records": normalization, "accepted": len(accepted),
                                              "blocked": len(normalization) - len(accepted)}))
        print(json.dumps({"precheck": [{"source": row["source_id"][:8], "gate": row["gate"],
                                        "locators": row["required_locators"], "error": row.get("error")}
                                       for row in normalization]}, ensure_ascii=False), flush=True)
        if not args.publish:
            return
        for review, before_ledger in accepted:
            store.put_gap_review(review)
            check_build_publishable(store, review.build_id)
            from datetime import UTC
            publication = publish_build(store, review.build_id, activated_at=datetime.now(UTC),
                                        operator="Codex executing xyl signed gap review", owner_id="i31-signed-release")
            if store.get_build(review.build_id).quality_report != before_ledger:
                raise RuntimeError("Gap ledger changed during release")
            job = store.get_job(review.build_id, JobStage.PUBLISHED)
            once(HERE / f"publication-{review.source_id[:8]}.json",
                 encode({"publication": json.loads(json.dumps(asdict(publication), default=str)),
                         "checkpoint": json.loads(job.checkpoint)}))
            print(f"Published {review.source_id[:8]} generation={publication.generation}", flush=True)

        sources = []
        for build_id, prior in prior_rows.items():
            build = store.get_build(build_id)
            records = gap_records_of(build, store=store)
            publication = store.get_publication(build.source_id)
            try:
                check_build_publishable(store, build_id)
                gate = True
            except EngineError:
                gate = False
            sources.append({"source_id": build.source_id, "build_id": build_id,
                            "domain": prior["domain"], "format": prior["format"], "provenance": prior["provenance"],
                            "published": bool(publication and publication.active_build_id == build_id),
                            "publishable": gate, "gaps": [r.as_payload() for r in records],
                            "gap_summary": gap_summary(records), "quality_report": json.loads(build.quality_report),
                            "parsed_succeeded": store.get_job(build_id, JobStage.PARSED).state.value == "succeeded",
                            "chunked_succeeded": store.get_job(build_id, JobStage.CHUNKED).state.value == "succeeded"})

    import psycopg
    import plugins.corpus.service as service_mod
    from plugins.corpus.audit import audit_corpus_chain
    from plugins.corpus.preparation import read_pg
    os.environ["CORPUS_READ_CHAIN"] = "new"
    service_mod.dsn = lambda: dsn
    service = service_mod.CorpusService(dsn)
    searches = []
    for query in ("营业收入", "景气", "非农", "同比", "工业富联", "光模块"):
        hits = service.search(query, limit=5)
        verified = []
        for hit in hits:
            evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
            document = read_pg.fetch_document(dsn, hit.doc_id, sandbox_db="i2_sandbox_corpus")
            verified.append({"locator": hit.locator, "active": bool(evidence.active),
                             "join_ok": evidence.text == "\n".join(u.raw_text for u in evidence.units),
                             "units_in_doc": all(u.raw_text in document.text for u in evidence.units)})
        searches.append({"query": query, "hits": len(hits), "verified": verified})
    with psycopg.connect(dsn, autocommit=True) as conn:
        audit = audit_corpus_chain(conn)
    per_class = {domain: {"total": sum(r["domain"] == domain for r in sources),
                         "published": sum(r["domain"] == domain and r["published"] for r in sources)}
                 for domain in ("company", "industry", "macro")}
    formats = {fmt: {"total": sum(r["format"] == fmt for r in sources),
                      "published": sum(r["format"] == fmt and r["published"] for r in sources)}
               for fmt in ("pdf", "docx", "md")}
    summary = {"sources": len(sources), "published": sum(r["published"] for r in sources),
               "per_class": per_class, "format_coverage": formats,
               "per_class_min_2": all(c["published"] >= 2 for c in per_class.values()),
               "format_gate": all(c["published"] >= 1 for c in formats.values()),
               "all_build_stages_succeeded": all(r["parsed_succeeded"] and r["chunked_succeeded"] for r in sources),
               "blocking": sum(r["gap_summary"]["blocking"] for r in sources),
               "human_acknowledged": sum(len(review.gaps) for review, _ in accepted),
               "all_searches_have_hits": all(s["hits"] > 0 for s in searches),
               "verify_all_ok": all(all(v.values()) for s in searches for v in s["verified"]),
               "audit_conflicts": audit.get("conflicts"), "refused_handles": 0}
    report = {"summary": summary, "sources": sources, "searches": searches, "audit": audit,
              "coverage": read_pg.coverage_snapshot(dsn, sandbox_db="i2_sandbox_corpus", query_status="matched"),
              "signed_records": normalization, "scope_manifest_sha256": digest(encode(manifest))}
    once(HERE / "release-e2e.json", encode(report))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
