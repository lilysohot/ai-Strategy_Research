"""Add stable first-ingestion timestamps without inventing historical dates.

Run with ``uv run python -m plugins.corpus.preparation.ingestion_schema``.
The existing explicit CORPUS_TARGET_DB guard applies. No migration runs on reads.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

# Lock both tables so backfill and trigger installation are atomic with publication.
MIGRATION_SQL = """
LOCK TABLE corpus.corpus_publications, corpus.corpus_sources IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE corpus.corpus_sources ADD COLUMN IF NOT EXISTS ingested_at timestamptz;
ALTER TABLE corpus.corpus_sources ADD COLUMN IF NOT EXISTS ingestion_tracking_started
 boolean NOT NULL DEFAULT false;
UPDATE corpus.corpus_sources s SET ingestion_tracking_started=true
 WHERE NOT EXISTS (SELECT 1 FROM corpus.corpus_publications p WHERE p.source_id=s.source_id);
ALTER TABLE corpus.corpus_sources ALTER COLUMN ingestion_tracking_started SET DEFAULT true;
COMMENT ON COLUMN corpus.corpus_sources.ingested_at IS
 'First successful corpus publication; immutable across rebuild/retirement. NULL means historical time unknown or never published.';
UPDATE corpus.corpus_sources s SET ingested_at=p.activated_at
FROM corpus.corpus_publications p
WHERE s.source_id=p.source_id AND s.ingested_at IS NULL
  AND p.generation=1 AND p.active_build_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_ingested_at ON corpus.corpus_sources(ingested_at)
 WHERE ingested_at IS NOT NULL;
CREATE OR REPLACE FUNCTION corpus.record_first_ingestion() RETURNS trigger
 LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.active_build_id IS NOT NULL THEN
   UPDATE corpus.corpus_sources SET ingested_at=COALESCE(ingested_at, NEW.activated_at)
   WHERE source_id=NEW.source_id AND (ingestion_tracking_started OR NEW.generation=1);
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER record_first_ingestion
 AFTER INSERT OR UPDATE ON corpus.corpus_publications
 FOR EACH ROW EXECUTE FUNCTION corpus.record_first_ingestion();
"""


def migrate(conn: psycopg.Connection, target: str) -> dict[str, int]:
    from plugins.corpus.preparation.search_pg import _check_target

    _check_target(conn, target)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute(MIGRATION_SQL)
        cur.execute(
            "SELECT count(*),count(s.ingested_at) FROM corpus.corpus_sources s "
            "JOIN corpus.corpus_publications p USING(source_id) WHERE p.active_build_id IS NOT NULL"
        )
        row = cur.fetchone()
        assert row is not None
        total, known = row
    return {
        "active_sources": total,
        "known_ingestion_times": known,
        "unknown_ingestion_times": total - known,
    }


def main() -> None:
    import psycopg
    from dotenv import load_dotenv

    from plugins.corpus.preparation.pg_target import resolve_target_db
    from plugins.corpus.service import dsn

    load_dotenv()
    with psycopg.connect(dsn(), autocommit=True, connect_timeout=10) as conn:
        print(json.dumps(migrate(conn, resolve_target_db())))


if __name__ == "__main__":
    main()
