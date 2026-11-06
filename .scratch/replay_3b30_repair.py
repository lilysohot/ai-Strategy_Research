import json
from pathlib import Path

from plugins.tools._verification import (
    project_checks, reset_verification_scope, set_verification_scope,
    validate_results, verification_label_findings,
)
from plugins.tools._web_handoff import render_web_handoff

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/3b30ebfd2e214ca19cc60e97ec36c12c/run/agent')
jobs = {j['job_id']: j for p in (root / 'team-results').rglob('*.json')
        for j in [json.loads(p.read_text())]}
projections = project_checks([
    {'job_id': j['job_id'], 'status': 'completed',
     'verification_checks': j['metadata'].get('verification_checks', []),
     'verification_events': j['metadata'].get('verification_events', [])}
    for j in sorted(jobs.values(), key=lambda j: int(j['job_id'].rsplit('.', 1)[1]))
])['checks']
review = next(j for j in jobs.values() if j['job_id'].endswith('.7'))
checks = review['metadata']['verification_checks']
sources = {s['key']: jobs[s['job_id']]['metadata'].get('web_evidence', [])
           for c in checks for s in [c['subject'], *c['evidence']] if s.get('job_id')}
focus = '\n'.join(c['subject'].get('text', '') for c in checks)
prompt = render_web_handoff(sources, focus_text=focus)
market = next(j for j in jobs.values() if j['job_id'].endswith('.1'))
metrics = {}
for suffix in ('DGS2', 'DGS10'):
    rec = next(r for r in market['metadata']['web_evidence'] if r['source'].endswith('/' + suffix))
    metrics[suffix] = {'full_body_delivered': rec['text'] in prompt, 'chars': len(rec['text'])}
    assert metrics[suffix]['full_body_delivered'], suffix
main = [json.loads(line) for line in (root / 'trajectories/main_agent.jsonl').read_text().splitlines()]
deliveries = [c for row in main if row['t'] == 'llm' for c in row.get('tool_calls', [])
              if c['name'] == 'deliver_answer']
findings = verification_label_findings(projections, deliveries[-1]['args']['content'])
assert any('已核验事实' in f['match'] for f in findings)
assert any('逐项核对过' in f['match'] for f in findings)
recovered = []
for suffix, jobnum in [('t02', 6), ('t05', 9)]:
    job = next(j for j in jobs.values() if j['job_id'].endswith('.' + str(jobnum)))
    rows = [json.loads(line) for line in (root / f'trajectories/subagents/fact_verifier.{suffix}.jsonl').read_text().splitlines()]
    for row in rows:
        if row['t'] != 'llm':
            continue
        for call in row.get('tool_calls', []):
            if call['name'] != 'submit_report':
                continue
            results = call['args'].get('verification_results') or []
            if not any('unresolved_issues' in (r.get('scope_assessment') or {}) for r in results):
                continue
            token = set_verification_scope(job['job_id'], {'verification_checks': job['metadata']['verification_checks']})
            try:
                accepted = validate_results(results)
                recovered.extend({'check_id': r['check_id'], 'verdict': r['verdict'], 'issues': r['unresolved_issues']} for r in accepted)
            finally:
                reset_verification_scope(token)
assert len(recovered) == 2
out = {'run_id': '3b30ebfd2e214ca19cc60e97ec36c12c', 'short_evidence': metrics,
       'handoff_chars': len(prompt), 'label_findings': findings, 'recovered_submissions': recovered,
       'scope': 'Offline protocol replay only; no new model verdict or factual market validation.'}
Path('.scratch/team-3b30-replay.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps(out, ensure_ascii=False, indent=2))
