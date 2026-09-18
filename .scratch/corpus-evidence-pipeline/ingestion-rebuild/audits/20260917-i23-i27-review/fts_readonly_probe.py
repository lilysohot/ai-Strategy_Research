"""Only SELECT expressions in the named sandbox; never DDL/DML or source reads."""

import json
from pathlib import Path

from dotenv import dotenv_values

from plugins.corpus.preparation.guard import install

ROOT = Path(__file__).resolve().parents[5]
install(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-sandbox.json")

import psycopg  # noqa: E402

password = dotenv_values(ROOT / ".env").get("CORPUS_DB_PASSWORD")
if not password:
    raise SystemExit("Read-only probe unavailable: sandbox password not configured")

try:
    with psycopg.connect(
        host="127.0.0.1", port=543, dbname="i2_sandbox_corpus", user="postgres",
        password=password, connect_timeout=3, autocommit=True,
        options="-c default_transaction_read_only=on -c statement_timeout=3000",
    ) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_setting('transaction_read_only')")
        target = cur.fetchone()
        if target != ("i2_sandbox_corpus", "on"):
            raise RuntimeError("Wrong target or not read-only")
        cur.execute("SELECT datname FROM pg_database WHERE datname = 'apodex'")
        if cur.fetchone() is not None:
            raise RuntimeError("Production marker present")
        for query in ("23.5", "23.5%", "增长 23.5%", "同比增长"):
            cur.execute(
                "SELECT to_tsvector('zhcfg', %s)::text, "
                "websearch_to_tsquery('zhcfg', %s)::text, "
                "to_tsvector('zhcfg', %s) @@ websearch_to_tsquery('zhcfg', %s)",
                ("同比增长23.5%".replace("%", " "), query,
                 "同比增长23.5%".replace("%", " "), query),
            )
            vector, tsquery, matched = cur.fetchone()
            print(json.dumps({"query": query, "vector": vector, "tsquery": tsquery,
                              "matched": matched}, ensure_ascii=False))
except Exception as exc:
    # Connection errors can contain credentials or environment details: redact.
    print(f"Read-only probe failed: {type(exc).__name__}")
    raise SystemExit(1) from None
