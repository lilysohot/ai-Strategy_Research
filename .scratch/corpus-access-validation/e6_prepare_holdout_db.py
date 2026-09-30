"""Build the frozen E6 holdout sources in an isolated corpus database.

This script never writes the production corpus database.  It creates (if
missing) ``e6_holdout_corpus``, records the already-frozen E2 source-selection
decision, runs the production reader/clean/chunk engine, and publishes only
builds accepted by the normal fail-closed publication gate.  Gate failures are
reported and are never bypassed or converted into synthetic human reviews.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TARGET_DB = "e6_holdout_corpus"
ARCHIVE = HERE / "e6-holdout-archive"
RESULT = HERE / "e6-holdout-build.json"
CORPUS_SCHEMA = (
    ROOT
    / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/sandbox_schema.sql"
)

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = TARGET_DB
os.environ.pop("PGOPTIONS", None)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from plugins.corpus.preparation.admission import load_admission_policy  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
)
from plugins.corpus.preparation.engine import (  # noqa: E402
    DEFAULT_LEASE,
    EngineError,
    PlanEntry,
    check_build_publishable,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.service import _I2_POLICY_PATH, CorpusService, dsn  # noqa: E402


def _target_dsn() -> tuple[str, str]:
    base = conninfo_to_dict(dsn())
    admin = make_conninfo(**{**base, "dbname": "postgres"})
    target = make_conninfo(**{**base, "dbname": TARGET_DB})
    return admin, target


def _ensure_database(admin_dsn: str) -> bool:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TARGET_DB,)
        ).fetchone()
        if exists:
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TARGET_DB)))
        return True


def _ensure_corpus_schema(target_dsn: str) -> bool:
    with psycopg.connect(target_dsn) as conn:
        exists = conn.execute("SELECT to_regclass('corpus.corpus_sources')").fetchone()[0]
        if exists is not None:
            return False
        conn.execute(CORPUS_SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
        return True


def _inputs() -> list[tuple[dict, Path]]:
    rows = json.loads((HERE / "e2_holdout_targets.json").read_text(encoding="utf-8"))
    inventory = json.loads((HERE / "e2-inventory.json").read_text(encoding="utf-8"))
    file_by_hash = {row["sha256"]: row["file"] for row in inventory["entries"]}
    out: list[tuple[dict, Path]] = []
    for row in rows:
        path = ROOT / "data" / "corpus" / file_by_hash[row["doc_identity"]]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["doc_identity"]:
            raise RuntimeError(f"holdout source hash mismatch: {path.name}")
        out.append((row, path))
    return out


def _decision(row: dict, source_id: str) -> ReviewedDecision:
    domain = ResearchDomain(str(row["domain"]))
    return ReviewedDecision(
        decision_id=f"e6-source-page-verified-{source_id[:16]}",
        source_id=source_id,
        reviewer="e2-frozen-source-page-review",
        reviewed_at=datetime(2026, 9, 30, tzinfo=UTC),
        decision=ReviewDecision.ADMITTED,
        rationale=(
            "Frozen E2 holdout selection: source-page targets were verified before E6; "
            "this decision is scoped to the isolated holdout database."
        ),
        material_type=MaterialType.RESEARCH_REPORT,
        research_domain=domain,
    )


def main() -> int:
    admin_dsn, target_dsn = _target_dsn()
    created = _ensure_database(admin_dsn)
    os.environ["CORPUS_DSN"] = target_dsn

    service = CorpusService(target_dsn)
    service.ensure_prerequisites()
    created_schema = _ensure_corpus_schema(target_dsn)
    store = PgStore(target_dsn, sandbox_db=TARGET_DB)
    policy = load_admission_policy(_I2_POLICY_PATH)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for row, path in _inputs():
        source_id = str(row["doc_identity"])
        decision = _decision(row, source_id)
        store.put_reviewed_decision(decision)
        record: dict[str, object] = {
            "sample_id": row["sample_id"],
            "source_id": source_id,
            "file": path.name,
            "domain": row["domain"],
        }
        try:
            plan = plan_builds(
                [
                    PlanEntry(
                        path=str(path),
                        domain_hint=ResearchDomain(str(row["domain"])),
                        review_decision_ids=(decision.decision_id,),
                    )
                ],
                policy=policy,
            )
            outcome = execute_builds(
                store,
                plan,
                policy=policy,
                archive_root=ARCHIVE,
                owner_id="e6-holdout-builder",
                now=datetime.now(UTC),
                lease=DEFAULT_LEASE,
            ).outcomes[0]
            record.update(
                {
                    "admission": outcome.admission.decision.value,
                    "unit_count": outcome.unit_count,
                    "chunk_count": outcome.chunk_count,
                }
            )
            if outcome.build is None:
                record["outcome"] = "not_in_scope"
            else:
                record["build_id"] = outcome.build.build_id
                try:
                    check_build_publishable(store, outcome.build.build_id)
                    publication = publish_build(
                        store,
                        outcome.build.build_id,
                        activated_at=datetime.now(UTC),
                        owner_id="e6-holdout-builder",
                    )
                    record.update(
                        {
                            "outcome": "published",
                            "generation": publication.generation,
                            "quality_report": json.loads(outcome.build.quality_report),
                        }
                    )
                except EngineError as exc:
                    record.update(
                        {
                            "outcome": "blocked_by_publish_gate",
                            "error": str(exc),
                            "quality_report": json.loads(outcome.build.quality_report),
                        }
                    )
        except Exception as exc:
            record.update({"outcome": "failed", "error": f"{type(exc).__name__}: {exc}"})
        results.append(record)
        print(json.dumps(record, ensure_ascii=False))

    summary = {
        "created_database": created,
        "created_schema": created_schema,
        "target_db": TARGET_DB,
        "sources": len(results),
        "published": sum(row.get("outcome") == "published" for row in results),
        "blocked": sum(row.get("outcome") == "blocked_by_publish_gate" for row in results),
        "failed": sum(row.get("outcome") == "failed" for row in results),
    }
    RESULT.write_text(
        json.dumps({"summary": summary, "sources": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"artifact={RESULT}")
    return 0 if summary["published"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
