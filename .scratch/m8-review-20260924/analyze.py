"""Independent spec gates and read-only control probe (isolated DB only)."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
OLD = BASE / 'audits/20260924-i51-scenarios'
sys.path.insert(0, str(OLD))
import i51_common as common
import psycopg

summary = {}
for path in sorted(OUT.glob('i51-s*-report.json')):
    data = json.loads(path.read_text())
    summary[path.name] = {'keys': list(data), 'script_gate': data.get('gate_passed'),
                          'summary': data.get('summary'), 'prod_unchanged': data.get('prod_unchanged')}
s1 = json.loads((OUT / 'i51-s1-rerun-report.json').read_text())
rows = s1['replay_build']['per_source']
summary['strict_rerun'] = {'all_build_ids_stable': all(r['build_id_same'] for r in rows),
                          'stable': sum(r['build_id_same'] for r in rows), 'total': len(rows),
                          'first_build_rebuild_plan': s1['rebuild_plan']}

with psycopg.connect(common.iso_dsn(common.load_env_credentials(), 'm8_review_20260924_s1'), autocommit=True) as conn:
    notices = []
    conn.add_notice_handler(lambda diag: notices.append(diag.message_primary))
    before = conn.execute('SHOW transaction_read_only').fetchone()[0]
    conn.execute('SET TRANSACTION READ ONLY')
    after = conn.execute('SHOW transaction_read_only').fetchone()[0]
    summary['original_readonly_control_probe'] = {'target': 'isolated 127.0.0.1:543',
        'before': before, 'after': after, 'notices': notices, 'writes_attempted': 0}

bindings = set()
for path in (BASE / 'freezes').glob('*.json'):
    try:
        obj = json.loads(path.read_text())
    except ValueError:
        continue
    for values in obj.get('binding', {}).values():
        if isinstance(values, dict):
            bindings.update(values)
summary['scenario_reproducibility_files_directly_bound_in_any_snapshot'] = {
    str(p.relative_to(ROOT)): str(p.relative_to(ROOT)) in bindings
    for p in [*sorted(OLD.glob('*.py')), common.GUARD]}
(OUT / 'independent-analysis.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps(summary, ensure_ascii=False, indent=2))
