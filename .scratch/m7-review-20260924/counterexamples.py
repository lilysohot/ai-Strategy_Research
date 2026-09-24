"""No-network counterexamples: import ordering and retired write entry."""
from pathlib import Path
import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.pop('CORPUS_TARGET_DB', None)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
from plugins.corpus import service
from plugins.corpus.preparation import read_pg, search_pg
from plugins.corpus.preparation.pg_target import resolve_target_db

os.environ['CORPUS_TARGET_DB'] = 'postgres'
result = {'late_config': {'resolved_now': resolve_target_db(),
                          'service_cached_target': service._I2_SANDBOX_DB,
                          'read_cached_target': read_pg._SANDBOX_DB,
                          'search_cached_target': search_pg._SANDBOX_DB}}
svc = service.CorpusService('postgresql://unused:unused@127.0.0.1:1/unused')
connection = MagicMock()
connection.__enter__.return_value = connection
connection.execute.return_value.fetchone.return_value = {'run_id': 1}
logging.disable(logging.CRITICAL)
with patch.object(svc, '_connect', return_value=connection), \
     patch.object(svc, '_ledger_json'), \
     patch.object(svc, 'ingest_dir', side_effect=RuntimeError('no CORPUS_I2_DSN configured')):
    outcome = svc._ingest_locked('/unused/review', trigger='manual', min_age=0)
sql = [call.args[0] for call in connection.execute.call_args_list]
result['retired_ingest_entry'] = {'exit_code': outcome['exit_code'],
    'sql': sql, 'commit_count': connection.commit.call_count,
    'writes_legacy_ingest_runs': any('INSERT INTO ingest_runs' in x for x in sql),
    'real_database_connections': 0}
output = json.dumps(result, ensure_ascii=False, indent=2)
(Path(__file__).parent / 'counterexamples.json').write_text(output)
print(output)
