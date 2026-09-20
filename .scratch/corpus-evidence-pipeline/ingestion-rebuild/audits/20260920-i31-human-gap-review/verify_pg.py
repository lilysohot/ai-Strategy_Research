"""Guarded PG synthetic round trip in a rollback-only transaction; no real approvals."""
from __future__ import annotations

import json
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]


def main() -> None:
    # Read credentials privately, then install the unchanged approved E2E guard.
    from dotenv import dotenv_values
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from plugins.corpus.preparation import guard

    values = dotenv_values(ROOT / ".env")
    connection = conninfo_to_dict(values["CORPUS_DSN"])
    dsn = make_conninfo("", user=connection.get("user"), password=connection.get("password"),
                        host="127.0.0.1", port=543, dbname="i2_sandbox_corpus", connect_timeout=5)
    guard.install(BASE / "guards/i3-e2e.json")
    from plugins.corpus.preparation.engine import gap_records_of
    from plugins.corpus.preparation.gaps import blocking_gaps
    from plugins.corpus.preparation.gap_review import review_template
    from plugins.corpus.preparation.read_pg import coverage_snapshot_on
    from plugins.corpus.preparation.repository_pg import PgStore

    tests = runpy.run_path(str(ROOT / "tests/test_corpus_gap_review.py"))
    workspace = HERE / "pg-synthetic"
    workspace.mkdir(exist_ok=True)
    with PgStore(dsn) as store:
        with store._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM corpus.corpus_sources")
            before = cur.fetchone()[0]
        with store._conn.transaction(force_rollback=True):
            pair = tests["_build_pdf"](workspace, store=store)
            tests["test_real_reader_build_publish_and_retry_keep_gap_and_audit"](pair)
            tests["test_immutable_review_and_generic_checkpoint_bypass"](pair)
            with store._conn.cursor() as cur:
                coverage = coverage_snapshot_on(cur, query_status="matched")
            assert coverage["processing"] == "scoped"
            assert "gap_regions_present" in coverage["reason_codes"]
        with store._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM corpus.corpus_sources")
            after = cur.fetchone()[0]
        assert before == after

        # Read only the eight build IDs in the approved E2E audit. Export unsigned
        # templates for blockers; never fill any human field or modify their DB rows.
        old = json.loads((BASE / "audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.json").read_text())
        def build_ids(value):
            if isinstance(value, dict):
                if isinstance(value.get("build_id"), str):
                    yield value["build_id"]
                for child in value.values():
                    yield from build_ids(child)
            elif isinstance(value, list):
                for child in value:
                    yield from build_ids(child)
        templates = []
        for build_id in sorted(set(build_ids(old))):
            build = store.get_build(build_id)
            assert build is not None, "approved build no longer exists; template binding unavailable"
            records = gap_records_of(build, store=store)
            if blocking_gaps(records):
                path = HERE / f"unsigned-{build.source_id[:8]}.json"
                path.write_text(json.dumps(review_template(build, records), ensure_ascii=False, indent=2) + "\n")
                templates.append({"file": path.name, "build_id": build_id,
                                  "source_id": build.source_id, "blocking": len(blocking_gaps(records))})
        assert len(templates) == 4 and sum(t["blocking"] for t in templates) == 13
    result = {"verdict": "PASS", "synthetic_pg_roundtrip": True, "rollback_residue": after - before,
              "real_review_records_written": 0, "real_sources_published": 0,
              "unsigned_templates": templates, "per_class_min_2": False}
    (HERE / "pg-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
