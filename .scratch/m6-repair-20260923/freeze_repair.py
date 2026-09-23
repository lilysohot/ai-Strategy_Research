"""Prepare the r5d candidate; refuse to rewrite it once final validation seals it."""
from pathlib import Path
from datetime import datetime
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes'
if (OUT / 'freeze-sealed.json').exists():
    raise RuntimeError('r5d is sealed. Further changes require a new append-only revision.')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def binding(paths):
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}

index = json.loads((BASE / 'freeze-manifest.json').read_text())
old_index = OUT / 'before-index.json'
if not old_index.exists():
    if any(x['snapshot_id'] == 'i0c-r5d' for x in index['snapshots']):
        raise RuntimeError('Cannot archive an index that already includes the new revision')
    old_index.write_bytes((BASE / 'freeze-manifest.json').read_bytes())
original = json.loads(old_index.read_text())
if [x for x in index['snapshots'] if x['snapshot_id'] != 'i0c-r5d'] != original['snapshots']:
    raise RuntimeError('Historical index entries changed')
for entry in original['snapshots']:
    if sha(BASE / entry['file']) != entry['sha256']:
        raise RuntimeError('Historical snapshot changed: ' + entry['snapshot_id'])

archives = sorted(p for p in (OUT / 'before').rglob('*') if p.is_file())
write(OUT / 'before-manifest.json', {str(p.relative_to(OUT/'before')): sha(p) for p in archives})
impl = [ROOT / p for p in [
    'plugins/corpus/preparation/read_pg.py', 'plugins/corpus/preparation/cross_boundary.py',
    'plugins/corpus/service.py', 'plugins/tools/corpus_fetch.py',
    'tools/corpus_product_observations.py']]
tests = [ROOT / p for p in ['tests/test_corpus_selection.py', 'tests/test_corpus_authority_pg.py',
    'tests/test_corpus_context_integrity.py', 'tests/test_corpus_product_observations.py']]
docs = [ROOT / 'docs/plan' / p for p in ['corpus-ingestion-rebuild-tasks.md', 'claims-market-closed-loop-plan.md']]
protected = [BASE / e['file'] for e in original['snapshots']]
protected += [ROOT / p for p in ['plugins/corpus/scoring.py',
    'plugins/corpus/preparation/search_pg.py', 'plugins/corpus/preparation/negative_query.py',
    'plugins/tools/corpus_search.py',
    '.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json',
    '.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json',
    '.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl',
    '.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json',
    '.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json']]
manifest_path = OUT / 'repair-manifest.json'
manifest = {
    'snapshot_id': 'i0c-r5d', 'authority_rev': 'authority-context-2',
    'status': 'implementation_repaired_acceptance_failed', 'business_accepted': False,
    'authorization': 'User requested execution of the preceding repair plan; no new business signoff',
    'implementation': binding(impl), 'tests': binding(tests),
    'unchanged_assets': binding(protected),
    'product_results': json.loads((OUT/'product-evaluation-summary.json').read_text()),
    'full_suite': {'passed': 2912, 'failed': 2, 'skipped': 49,
        'existing_failures': ['test_market_hit_rate_is_100_percent', 'test_react_profile_binds_the_finance_tools']},
    'model_calls': 0,
    'not_executed': ['model preflight', 'model answer semantics', 'heldout tuning', 'production 5432 legacy golden', 'I4'],
}
write(manifest_path, manifest)
evidence = [p for p in OUT.iterdir() if p.is_file()
    and p.suffix in {'.py', '.json', '.md', '.log', '.txt', '.exit'}
    and not p.name.startswith('freeze-')]
# Negative controls can be generated against the candidate and bound before final validation.
if (OUT/'freeze-negative-controls.json').exists():
    evidence.append(OUT/'freeze-negative-controls.json')
snapshot = {
    'snapshot_id': 'i0c-r5d', 'revision': 'r5d', 'phase': 'i0c',
    'status': 'frozen_repair_acceptance_failed', 'business_accepted': False,
    'parent_snapshot': {'snapshot_id': 'i0c-r5c',
        'path': str((BASE/'i0c-r5c.json').relative_to(ROOT)), 'sha256': sha(BASE/'i0c-r5c.json')},
    'binding': {'m6_repair_implementation': binding(impl), 'm6_repair_tests': binding(tests),
        'm6_repair_state': binding(docs), 'm6_repair_archive': binding(archives),
        'm6_repair_evidence': binding(evidence),
        'freeze_validator': binding([BASE/'validate_i0c_freeze.py'])},
    'corrections': {
        'S1': 'Verify hashes for all selected contextual units before exposing authority text.',
        'F1': 'Single and batch fetch share contextual projection inside a readonly repeatable-read snapshot.',
        'F2': 'Actual registered tool observations for all labels; unchanged raw default queries, bounded limits, no synthetic NO_MATCH.',
        'historical_checks': 'Three historical read_pg/service assertions use archived bytes bound to previous effective hashes; current bytes verified by r5d.'},
    'notes': ['All historical snapshots and final manifest unchanged.',
        'Business gate remains failed; old signed r5c experiment results do not establish new product acceptance.',
        'No scoring, gold, threshold, search strategy, index or abstain default change.'],
    'm5_declaration': 'not_declared',
}
write(BASE/'i0c-r5d.json', snapshot)
old_row = next((x for x in index['snapshots'] if x['snapshot_id'] == 'i0c-r5d'), None)
index['snapshots'] = original['snapshots'] + [{
    'snapshot_id': 'i0c-r5d', 'file': 'i0c-r5d.json', 'sha256': sha(BASE/'i0c-r5d.json'),
    'parent_snapshot_id': 'i0c-r5c',
    'created_at': old_row['created_at'] if old_row else datetime.now().astimezone().isoformat()}]
write(BASE/'freeze-manifest.json', index)
print('Prepared i0c-r5d; historical snapshots unchanged; business_accepted=false')
