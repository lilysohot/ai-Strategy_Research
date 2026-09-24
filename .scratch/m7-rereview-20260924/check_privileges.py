"""Read-only privilege checks for retired evidence table, no writes."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
for key, value in dotenv_values(ROOT / '.env').items():
    if key.startswith('CORPUS_') and value is not None:
        os.environ.setdefault(key, value)
os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'
from plugins.corpus.service import dsn
import psycopg
with psycopg.connect(dsn()) as conn:
    assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
    assert conn.execute('SELECT current_database()').fetchone()[0] == 'postgres'
    user, superuser, can_insert, can_update = conn.execute(
        "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname=current_user), "
        "has_table_privilege(current_user,'public.corpus_evidence_runs','INSERT'), "
        "has_table_privilege(current_user,'public.corpus_evidence_runs','UPDATE')").fetchone()
    n = conn.execute('SELECT count(*) FROM public.corpus_evidence_runs').fetchone()[0]
    triggers = conn.execute(
        "SELECT tgname FROM pg_trigger WHERE tgrelid='public.corpus_evidence_runs'::regclass "
        "AND NOT tgisinternal").fetchall()
    result = {'current_user': user, 'superuser': superuser, 'can_insert_evidence': can_insert,
              'can_update_evidence': can_update, 'old_evidence_rows': n,
              'user_triggers': triggers, 'read_only_session': True}
(Path(__file__).parent / 'privileges.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
