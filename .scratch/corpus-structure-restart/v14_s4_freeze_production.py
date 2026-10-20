"""Capture the current corpus production baseline using a read-only transaction.

This script never prints or persists the DSN or credentials.  It aborts unless
the connected database matches CORPUS_TARGET_DB.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg import sql

from plugins.corpus.service import dsn


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/data_clean_dos/v14-s4-production-baseline.json"
PUBLIC_TABLES = (
    "documents",
    "blocks",
    "claims",
    "claims_v2",
    "claim_block_runs",
    "claim_block_runs_v2",
    "corpus_evidence_runs",
    "ingest_runs",
    "ingest_failures",
    "docs",
    "chinese_docs",
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _scalar(conn: psycopg.Connection[Any], query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return None if row is None else row[0]


def _table_count(conn: psycopg.Connection[Any], schema: str, table: str) -> int:
    query = sql.SQL("SELECT count(*) FROM {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table)
    )
    return int(conn.execute(query).fetchone()[0])


def main() -> None:
    load_dotenv(REPO / ".env", override=False)
    expected_db = os.environ.get("CORPUS_TARGET_DB", "").strip()
    if not expected_db:
        raise RuntimeError("CORPUS_TARGET_DB is required for a production snapshot")

    with psycopg.connect(dsn(), autocommit=False) as conn:
        conn.execute("BEGIN READ ONLY")
        actual_db = str(_scalar(conn, "SELECT current_database()"))
        if actual_db != expected_db:
            raise RuntimeError(
                f"database mismatch: CORPUS_TARGET_DB={expected_db!r}, current_database={actual_db!r}"
            )

        identity_row = conn.execute(
            """
            SELECT current_database(), current_setting('server_version'),
                   pg_is_in_recovery(), pg_current_wal_lsn()::text, now(),
                   pg_database_size(current_database()),
                   current_setting('transaction_read_only')
            """
        ).fetchone()
        assert identity_row is not None

        corpus_tables = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'corpus' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
        ]
        corpus_counts = {
            table: _table_count(conn, "corpus", table) for table in corpus_tables
        }

        publication_rows = conn.execute(
            """
            SELECT trim(p.source_id::text), s.format, s.size_bytes, s.original_names,
                   p.current_decision_id, trim(p.active_build_id::text), p.generation,
                   p.activated_at, a.material_type, a.research_domain, a.scope_ref,
                   b.parse_rev, b.clean_rev, b.chunk_rev, b.index_rev,
                   b.config_fingerprint,
                   (SELECT count(*) FROM corpus.corpus_units u
                    WHERE u.build_id = p.active_build_id),
                   (SELECT count(*) FROM corpus.corpus_chunks c
                    WHERE c.build_id = p.active_build_id)
            FROM corpus.corpus_publications p
            JOIN corpus.corpus_sources s ON s.source_id = p.source_id
            JOIN corpus.corpus_admissions a ON a.decision_id = p.current_decision_id
            JOIN corpus.corpus_builds b ON b.build_id = p.active_build_id
            ORDER BY p.source_id
            """
        ).fetchall()
        publications = []
        for row in publication_rows:
            publications.append(
                {
                    "source_id": row[0],
                    "format": row[1],
                    "size_bytes": row[2],
                    "original_names": row[3],
                    "current_decision_id": row[4],
                    "active_build_id": row[5],
                    "generation": row[6],
                    "activated_at": row[7].isoformat(),
                    "material_type": row[8],
                    "research_domain": row[9],
                    "scope_ref": row[10],
                    "parse_rev": row[11],
                    "clean_rev": row[12],
                    "chunk_rev": row[13],
                    "index_rev": row[14],
                    "config_fingerprint": row[15],
                    "unit_count": row[16],
                    "chunk_count": row[17],
                }
            )

        job_states = {
            str(state): int(count)
            for state, count in conn.execute(
                "SELECT state, count(*) FROM corpus.corpus_jobs GROUP BY state ORDER BY state"
            ).fetchall()
        }
        running_jobs = int(job_states.get("running", 0))

        public_counts: dict[str, int | None] = {}
        for table in PUBLIC_TABLES:
            exists = bool(
                _scalar(conn, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
            )
            public_counts[table] = _table_count(conn, "public", table) if exists else None

        extensions = {
            str(name): str(version)
            for name, version in conn.execute(
                "SELECT extname, extversion FROM pg_extension ORDER BY extname"
            ).fetchall()
        }

        privileges = conn.execute(
            """
            SELECT
              has_schema_privilege(current_user, 'corpus', 'USAGE'),
              has_schema_privilege(current_user, 'corpus', 'CREATE'),
              bool_or(has_table_privilege(current_user, format('corpus.%I', table_name), 'SELECT')),
              bool_or(has_table_privilege(current_user, format('corpus.%I', table_name), 'INSERT')),
              bool_or(has_table_privilege(current_user, format('corpus.%I', table_name), 'UPDATE')),
              bool_or(has_table_privilege(current_user, format('corpus.%I', table_name), 'DELETE'))
            FROM information_schema.tables
            WHERE table_schema = 'corpus' AND table_type = 'BASE TABLE'
            """
        ).fetchone()
        assert privileges is not None

        snapshot = {
            "artifact": "v14-s4-production-baseline",
            "schema": "corpus-v14-s4-production-baseline-v1",
            "captured_at": identity_row[4].isoformat(),
            "capture_mode": "explicit BEGIN READ ONLY; no model calls; no writes",
            "status": "PRODUCTION_BASELINE_FROZEN_PRE_CUTOVER",
            "target": {
                "database": identity_row[0],
                "schema": "corpus",
                "server_version": identity_row[1],
                "in_recovery": identity_row[2],
                "wal_lsn": identity_row[3],
                "database_size_bytes": identity_row[5],
                "transaction_read_only": identity_row[6],
                "target_env_matches_current_database": actual_db == expected_db,
            },
            "code_at_capture": {
                "head": _git("rev-parse", "HEAD"),
                "branch": _git("branch", "--show-current"),
                "release_candidate_tag_commit": _git("rev-list", "-n", "1", "corpus-v14-s4-rc1"),
            },
            "corpus_schema": {
                "table_count": len(corpus_tables),
                "tables": corpus_tables,
                "row_counts": corpus_counts,
                "active_publication_count": len(publications),
                "active_publications": publications,
                "job_state_counts": job_states,
                "running_jobs": running_jobs,
            },
            "retained_public_tables": public_counts,
            "extensions": extensions,
            "connection_role_capabilities": {
                "schema_usage": privileges[0],
                "schema_create": privileges[1],
                "any_table_select": privileges[2],
                "any_table_insert": privileges[3],
                "any_table_update": privileges[4],
                "any_table_delete": privileges[5],
                "note": "The capture transaction itself was read-only; role capabilities are recorded for cutover risk assessment without storing the role name."
            },
            "prior_cutover_evidence": {
                "manifest": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-cutover-manifest.json",
                "manifest_sha256": _sha256(
                    REPO
                    / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-cutover-manifest.json"
                ),
                "restore_verification": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i46-restore-verification.json",
                "restore_verification_sha256": _sha256(
                    REPO
                    / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i46-restore-verification.json"
                ),
            },
        }
        conn.rollback()

    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": snapshot["status"],
                "database": snapshot["target"]["database"],
                "transaction_read_only": snapshot["target"]["transaction_read_only"],
                "corpus_tables": snapshot["corpus_schema"]["table_count"],
                "active_publications": snapshot["corpus_schema"]["active_publication_count"],
                "running_jobs": snapshot["corpus_schema"]["running_jobs"],
                "output": str(OUT.relative_to(REPO)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
