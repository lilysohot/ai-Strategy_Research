"""Replay existing isolated-PG regression lanes; retain historical artifacts."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify'
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
m = load('m7_frozen_battery', OLD / 'run_tests.py')
m.HERE = OUT
m.load_i37_rebuild = lambda: load('m7_frozen_rebuild', OLD / 'i37_rebuild.py')
original_lane_env = m.lane_env
def lane_env(**kwargs):
    env = original_lane_env(**kwargs)
    env['CORPUS_TARGET_DB'] = ''
    return env
m.lane_env = lane_env
def restore():
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--restore'],
        cwd=ROOT, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                      'LANG': 'C.UTF-8', 'PYTHONPATH': str(ROOT),
                      'PYTHONDONTWRITEBYTECODE': '1', 'CORPUS_TARGET_DB': ''},
        capture_output=True, text=True, timeout=1200)
    (OUT / 'lane-restore.txt').write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError('Isolated sandbox restoration failed; inspect lane-restore.txt')
    return json.loads(proc.stdout.strip().splitlines()[-1])
m.restore_via_subprocess = restore
if '--restore' in sys.argv:
    print(json.dumps(m.restore_real_sources()))
elif '--supplement-ready' in sys.argv:
    legacy_dsn = m.ensure_d2d6_db()
    try:
        # Match the real legacy database's public.zhcfg prerequisite. Without
        # this, the first temporary schema creates a non-shared zhcfg and the
        # second schema cannot see it; record that first run separately.
        from plugins.corpus.service import CorpusService
        CorpusService(legacy_dsn).ensure_prerequisites()
        result = m.run_lane('supplement-audit-evidence-ready', [
            'tests/test_corpus_audit.py', 'tests/test_corpus_evidence_pipeline.py'],
            {**m.lane_env(guard=None, dsn=None), 'CORPUS_DSN': legacy_dsn,
             'CORPUS_I2_DSN': m.build_dsn(), 'PYTHON_DOTENV_DISABLED': '1'})
    finally:
        dropped = m.drop_d2d6_db()
    (OUT / 'supplement-ready.json').write_text(json.dumps(
        {'lane': result, 'prerequisite': 'public.zhcfg initialized',
         'temporary_db_removed': dropped}, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
elif '--supplement' in sys.argv:
    results = []
    try:
        dsn = m.build_dsn()
        legacy_dsn = m.ensure_d2d6_db()
        results.append(m.run_lane('supplement-audit-evidence', [
            'tests/test_corpus_audit.py', 'tests/test_corpus_evidence_pipeline.py'],
            {**m.lane_env(guard=None, dsn=None), 'CORPUS_DSN': legacy_dsn,
             'CORPUS_I2_DSN': dsn, 'PYTHON_DOTENV_DISABLED': '1'}))
        results.append(m.run_lane('supplement-gap', ['tests/test_corpus_gap_dispositions.py'],
            m.lane_env(guard=m.GUARD_I2V, dsn=dsn)))
        results.append(m.run_lane('fullchain-confirm', [
            str(OLD.parent / '20260918-i2-fullchain-review/test_fullchain_probes.py')
            + '::test_control_full_chain_reaches_reference_free_evidence'],
            m.lane_env(guard=m.GUARD_I2V, dsn=dsn)))
    finally:
        m.drop_d2d6_db()
        restored = restore()
    output = {'lanes': results, 'restore': restored}
    (OUT / 'supplement-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))
else:
    try:
        code = m.main()
        path = OUT / 'i37-tests-results.json'
        result = json.loads(path.read_text())
        result['artifact'] = 'm7-independent-full-regression'
        result['reused_baseline'] = result.pop('frozen_version')
        result['tested_chain'] = 'i0c-r5j / HEAD d897d8f + initial staged/worktree changes'
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        (OUT / 'pg-battery.exit').write_text(str(code))
    finally:
        if not (OUT / 'i37-tests-results.json').exists():
            m.drop_d2d6_db()
            restore()
