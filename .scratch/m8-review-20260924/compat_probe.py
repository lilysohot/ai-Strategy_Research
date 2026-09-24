"""Verify init/audit/CSV consistency on a disposable isolated database."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i51-scenarios')]
import i51_common as common
import psycopg
from psycopg import sql
from plugins.corpus.service import CorpusService
from plugins.corpus.audit import run_audit

DB = 'm8_review_20260924_compat'
credentials = common.load_env_credentials()
admin = common.iso_dsn(credentials, 'postgres')
dsn = common.iso_dsn(credentials, DB)
result = {}
with psycopg.connect(admin, autocommit=True) as conn:
    names = {r[0] for r in conn.execute('SELECT datname FROM pg_database')}
    assert conn.info.host == '127.0.0.1' and conn.info.port == 543
    assert 'apodex' not in names and 'i0b2_verify_postgres' in names and DB not in names
    conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(DB)))
try:
    service = CorpusService(dsn)
    service.init_db()
    audit, code = run_audit(dsn, jsonl_path='')
    result['fresh_init_audit'] = {'exit_code': code, 'conflicts': audit['conflicts'],
                                 'coverage': audit['completeness']['backup_coverage']}
    try:
        service.backup(OUT / 'fresh-init-csv', mode='csv')
        result['csv_backup'] = {'passed': True}
    except Exception as exc:
        result['csv_backup'] = {'passed': False, 'error_type': type(exc).__name__,
                                'message': str(exc).replace(dsn, '<redacted>')}
finally:
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(DB)))
    result['temporary_db_removed'] = True
    (OUT / 'compat-probe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
