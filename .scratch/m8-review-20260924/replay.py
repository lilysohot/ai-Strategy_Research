"""Re-execute I5 scenarios in fresh review databases; never overwrite recorded runs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
OLD = BASE / 'audits/20260924-i51-scenarios'
DBS = tuple(f'm8_review_20260924_s{i}' for i in range(1, 5))
FILES = ['i51_s1_rerun.py', 'i51_s2_srcchange.py', 'i51_s3_newrule.py', 'i51_s4_idxreb.py']
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), str(OLD)]
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHON_DOTENV_DISABLED'] = '1'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

import i51_common as common
credentials = common.load_env_credentials()

def readonly_snapshot(dsn):
    import psycopg
    with psycopg.connect(dsn, options='-c default_transaction_read_only=on') as conn:
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        cur = conn.execute(common.PROD_COUNTS_SQL)
        counts = dict(zip([d.name for d in cur.description], cur.fetchone()))
        active = dict(conn.execute('SELECT source_id, active_build_id FROM corpus.corpus_publications ORDER BY 1').fetchall())
    return {'counts': counts, 'active_by_source': active}

mode = sys.argv[1]
if mode == 'setup':
    setup = load('review_setup', OLD / 'i51_setup_dbs.py')
    for key in ('CORPUS_DB_USER', 'CORPUS_DB_PASSWORD'):
        os.environ[key] = credentials[key]
    import psycopg
    with psycopg.connect(common.iso_dsn(credentials, 'postgres')) as conn:
        existing = {r[0] for r in conn.execute('SELECT datname FROM pg_database')}
        assert not existing.intersection(DBS), 'Review database already exists'
    setup.EXPECTED_DBS.update(DBS)
    setup.SCENARIO_DBS = DBS
    setup.OUT = OUT / 'setup.json'
    # Capture version/config/code identity before any build.
    files = [*OLD.glob('*.py'), common.GUARD, common.MANIFEST, common.DEV_POLICY,
             *ROOT.glob('plugins/corpus/**/*.py'), BASE / 'freezes/i0c-r5o.json', Path(__file__)]
    manifest = {'head': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
                'chain': 'i0c-r5o', 'databases': DBS,
                'changes_to_replay': ['new database names and output paths',
                     'production snapshot uses session read-only instead of ineffective autocommit SET TRANSACTION'],
                'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (OUT / 'run-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    raise SystemExit(setup.main())
elif mode in {'1','2','3','4'}:
    i = int(mode)-1
    common.prod_readonly_snapshot = readonly_snapshot
    module = load('review_scenario', OLD / FILES[i])
    module.HERE = OUT
    module.DB = DBS[i]
    module.OUT = OUT / module.OUT.name
    if i == 1:
        module.MUTATED = OUT / 's2-mutated'
        module.S2_ARCHIVE = OUT / 's2-archive'
    raise SystemExit(module.main())
elif mode == 'cleanup':
    import psycopg
    from psycopg import sql
    with psycopg.connect(common.iso_dsn(credentials, 'postgres'), autocommit=True) as conn:
        existing = {r[0] for r in conn.execute('SELECT datname FROM pg_database')}
        assert conn.info.host == '127.0.0.1' and conn.info.port == 543
        assert 'apodex' not in existing and 'i0b2_verify_postgres' in existing
        for db in DBS:
            if db in existing:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(db)))
        remaining = {r[0] for r in conn.execute('SELECT datname FROM pg_database')}
    (OUT / 'cleanup.json').write_text(json.dumps({'dropped': DBS, 'all_absent': not remaining.intersection(DBS)}, indent=2)+'\n')
else:
    raise SystemExit('unknown mode')
