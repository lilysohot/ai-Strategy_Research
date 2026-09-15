"""User-authorized P2-B incident metadata audit. No DDL/DML or corpus text output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from plugins.corpus.service import dsn


def inspect() -> dict[str, object]:
    configured = dsn()
    parameters = conninfo_to_dict(configured)
    report: dict[str, object] = {
        "version": "p2b-pg-readonly-1",
        "scope": "metadata only; no corpus text or DDL/DML; explicit rollback",
        "target_resolution": "current same-environment service.dsn(); prior connection identity was not recorded",
        "configured_target": {k: parameters.get(k) for k in ("host", "port", "dbname", "user")},
        "queries": {},
    }
    results: dict[str, object] = {}
    with psycopg.connect(
        configured,
        options="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000",
        application_name="r2_p2b_authorized_readonly_audit",
        connect_timeout=5,
        autocommit=True,
        row_factory=dict_row,
    ) as connection:
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        assert connection.execute("SHOW transaction_read_only").fetchone() == {
            "transaction_read_only": "on"
        }

        def query(name: str, statement: str, params: tuple[object, ...] = ()) -> None:
            connection.execute("SAVEPOINT audit_query")
            try:
                results[name] = connection.execute(statement, params or None).fetchall()
            except psycopg.Error as exc:
                connection.execute("ROLLBACK TO SAVEPOINT audit_query")
                results[name] = {"unavailable_sqlstate": exc.sqlstate}
            finally:
                connection.execute("RELEASE SAVEPOINT audit_query")

        query(
            "identity",
            "SELECT current_database() AS database, current_user AS role, inet_server_addr()::text AS server_address, inet_server_port() AS server_port, current_setting('server_version') AS version, pg_postmaster_start_time() AS server_started, now() AS observed_at, current_setting('transaction_read_only') AS read_only",
        )
        query(
            "cluster",
            "SELECT system_identifier::text, pg_control_version, catalog_version_no FROM pg_control_system()",
        )
        query(
            "settings",
            "SELECT name, setting FROM pg_settings WHERE name = ANY(%s) ORDER BY name",
            (
                [
                    "archive_mode",
                    "logging_collector",
                    "log_destination",
                    "log_statement",
                    "log_min_duration_statement",
                    "log_connections",
                    "log_disconnections",
                    "log_directory",
                    "log_filename",
                    "track_commit_timestamp",
                    "shared_preload_libraries",
                ],
            ),
        )
        query(
            "schemas",
            "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' ORDER BY nspname",
        )
        query(
            "extensions",
            "SELECT e.extname, e.extversion, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname",
        )
        query(
            "text_search_config",
            "SELECT n.nspname, c.cfgname, p.prsname FROM pg_ts_config c JOIN pg_namespace n ON n.oid=c.cfgnamespace JOIN pg_ts_parser p ON p.oid=c.cfgparser WHERE c.cfgname='zhcfg'",
        )
        query(
            "text_search_mapping",
            "SELECT n.nspname, c.cfgname, m.maptokentype, m.mapseqno, d.dictname FROM pg_ts_config c JOIN pg_namespace n ON n.oid=c.cfgnamespace JOIN pg_ts_config_map m ON m.mapcfg=c.oid JOIN pg_ts_dict d ON d.oid=m.mapdict WHERE c.cfgname='zhcfg' ORDER BY n.nspname,m.maptokentype,m.mapseqno",
        )
        query(
            "table_statistics",
            "SELECT schemaname, relname, n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd, n_tup_del, last_analyze, last_autoanalyze FROM pg_stat_user_tables ORDER BY schemaname,relname",
        )
        query(
            "database_statistics",
            "SELECT stats_reset, xact_commit, xact_rollback, tup_inserted, tup_updated, tup_deleted FROM pg_stat_database WHERE datname=current_database()",
        )
        query(
            "columns",
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY(%s) ORDER BY table_name,ordinal_position",
            (
                [
                    "documents",
                    "blocks",
                    "claims",
                    "claim_block_runs",
                    "corpus_evidence_runs",
                    "ingest_runs",
                    "ingest_failures",
                ],
            ),
        )
        for table in (
            "documents",
            "blocks",
            "claims",
            "claim_block_runs",
            "corpus_evidence_runs",
            "ingest_runs",
            "ingest_failures",
        ):
            query("count_" + table, f'SELECT count(*) AS rows FROM public."{table}"')
        query(
            "document_times",
            "SELECT min(ingested_at) AS first_ingested, max(ingested_at) AS last_ingested FROM public.documents",
        )
        query(
            "event_window_rows",
            "SELECT (SELECT count(*) FROM public.documents WHERE ingested_at >= %s AND ingested_at < %s) AS documents, (SELECT count(*) FROM public.corpus_evidence_runs WHERE created_at >= %s AND created_at < %s) AS evidence_runs, (SELECT count(*) FROM public.ingest_runs WHERE started_at >= %s AND started_at < %s) AS ingest_runs",
            ("2026-09-14T05:37:00Z", "2026-09-14T05:40:00Z") * 3,
        )
        query(
            "evidence_times",
            "SELECT min(created_at) AS first_created, max(created_at) AS last_created FROM public.corpus_evidence_runs",
        )
        query(
            "extra_table_counts",
            "SELECT (SELECT count(*) FROM public.claims_v2) AS claims_v2, (SELECT count(*) FROM public.claim_block_runs_v2) AS claim_block_runs_v2",
        )
        # Project only metadata columns from the known pre-incident local backup.
        backup = Path("data/corpus_full_backup_v2/documents.csv")
        with backup.open(newline="", encoding="utf-8") as stream:
            prior = {row["doc_id"]: row["content_hash"] for row in csv.DictReader(stream)}
        current = {
            row["doc_id"]: row["content_hash"]
            for row in connection.execute("SELECT doc_id, content_hash FROM public.documents")
        }
        results["backup_document_metadata_comparison"] = {
            "backup_file": str(backup),
            "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            "backup_rows": len(prior),
            "current_rows": len(current),
            "missing_ids": len(set(prior) - set(current)),
            "changed_content_hashes": sum(
                current[key] != value for key, value in prior.items() if key in current
            ),
            "additional_ids": len(set(current) - set(prior)),
            "limitation": "compares stored document metadata only, not block bodies or a pre-incident full snapshot",
        }
        query(
            "orphan_blocks",
            "SELECT count(*) AS rows FROM public.blocks b LEFT JOIN public.documents d USING(doc_id) WHERE d.doc_id IS NULL",
        )
        query(
            "orphan_claims",
            "SELECT count(*) AS rows FROM public.claims c LEFT JOIN public.documents d USING(doc_id) WHERE d.doc_id IS NULL",
        )
        query(
            "invalid_indexes",
            "SELECT n.nspname,c.relname,i.indisvalid,i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND (NOT i.indisvalid OR NOT i.indisready)",
        )
        query("current_logfile", "SELECT pg_current_logfile() AS path")
        query(
            "log_directory",
            "SELECT name,size,modification FROM pg_ls_logdir() ORDER BY modification DESC LIMIT 10",
        )
        query(
            "archiver",
            "SELECT archived_count,last_archived_wal,last_archived_time,failed_count,stats_reset FROM pg_stat_archiver",
        )
        connection.execute("ROLLBACK")
    report["queries"] = results
    report["transaction_ended"] = "rollback"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("new output required")
    try:
        result = inspect()
    except psycopg.Error as exc:
        raise SystemExit(
            f"read-only audit unavailable: {type(exc).__name__}, sqlstate={exc.sqlstate}"
        ) from None
    raw = json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
    with args.out.open("x", encoding="utf-8") as stream:
        stream.write(raw)
    print(raw)
    print("artifact_sha256=" + hashlib.sha256(raw.encode()).hexdigest())
