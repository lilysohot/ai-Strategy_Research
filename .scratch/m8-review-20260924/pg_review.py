"""Run original PG tests, restoring the existing isolated sandbox from a full dump."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify'
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location('original_pg_runner', OLD / 'run_tests.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.HERE = OUT
m.D2D6_DB = 'm8_review_20260924_legacy'
import psycopg
from psycopg import sql

dsn = m.build_dsn()
admin = f'postgresql://{m.build_admin_cred()}@127.0.0.1:543/postgres'
with psycopg.connect(admin) as conn:
    assert conn.info.host == '127.0.0.1' and conn.info.port == 543
    names = {r[0] for r in conn.execute('SELECT datname FROM pg_database')}
    assert 'apodex' not in names and 'i0b2_verify_postgres' in names
    assert m.D2D6_DB not in names
    user = conn.info.user
port = subprocess.check_output(['docker', 'port', 'corpus-db', '5432'], text=True)
assert port.strip().splitlines() and all(line.endswith(':543') for line in port.splitlines())

def snapshot():
    with psycopg.connect(dsn, options='-c default_transaction_read_only=on') as conn:
        tables = conn.execute("SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2").fetchall()
        result = {}
        for schema, table in tables:
            rows = conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t ORDER BY row_to_json(t)::text').format(sql.Identifier(schema), sql.Identifier(table))).fetchall()
            result[f'{schema}.{table}'] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
        return result

before = snapshot()
(OUT / 'sandbox-before.json').write_text(json.dumps(before, indent=2))
dump = OUT / 'sandbox-before.dump'
with dump.open('xb') as stream:
    subprocess.run(['docker','exec','corpus-db','pg_dump','-U',user,'-Fc','i2_sandbox_corpus'], stdout=stream, check=True, timeout=120)

def env(guard=None, legacy=None):
    e = m.lane_env(guard=guard, dsn=dsn)
    e.update(CORPUS_TARGET_DB='', PYTHON_DOTENV_DISABLED='1',
             CORPUS_DSN=legacy or 'postgresql://disabled:disabled@127.0.0.1:1/disabled?connect_timeout=1')
    return e

results = []
legacy_created = False
try:
    legacy = m.ensure_d2d6_db()
    legacy_created = True
    from plugins.corpus.service import CorpusService
    CorpusService(legacy).ensure_prerequisites()
    for label, tests, lane_env in [
        ('pg-search-live', ['tests/test_corpus_search_pg.py'], env(m.GUARD_I2V)),
        ('pg-fullchain', [str(OLD.parent / '20260918-i2-fullchain-review/test_fullchain_probes.py')], env(m.GUARD_I2V)),
        ('pg-hermetic', m.M5_HERMETIC_TESTS, env(m.GUARD_I2V)),
        ('pg-gap', ['tests/test_corpus_gap_dispositions.py'], env(m.GUARD_I2V)),
        ('pg-claims-metadata', m.M5_DSN_TESTS, env(legacy=legacy)),
        ('pg-audit-evidence', ['tests/test_corpus_audit.py','tests/test_corpus_evidence_pipeline.py'], env(legacy=legacy)),
    ]:
        result = m.run_lane(label, tests, lane_env)
        results.append(result)
        print(json.dumps(result), flush=True)
finally:
    if legacy_created:
        m.drop_d2d6_db()
    with dump.open('rb') as stream:
        proc = subprocess.run(['docker','exec','-i','corpus-db','pg_restore','-U',user,'--clean','--if-exists','--exit-on-error','-d','i2_sandbox_corpus'], stdin=stream, capture_output=True, text=True, timeout=180)
    (OUT / 'sandbox-restore.log').write_text(proc.stdout + proc.stderr)
    proc.check_returncode()
    after = snapshot()
    report = {'lanes': results, 'sandbox_restored_exact_table_contents': before == after,
              'after': after, 'dump_sha256': hashlib.sha256(dump.read_bytes()).hexdigest(),
              'legacy_db_removed': True}
    (OUT / 'pg-results.json').write_text(json.dumps(report, indent=2))
    assert before == after, 'Sandbox restoration mismatch'
