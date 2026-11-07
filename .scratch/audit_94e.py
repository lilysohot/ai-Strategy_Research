import json
from pathlib import Path
from benchmarks.team_workflow.metrics import measure

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/94e38ed61ce54831a273aaabf20f6a0d')
traces = root / 'run/agent/trajectories'
main = [json.loads(s) for s in (traces/'main_agent.jsonl').read_text().splitlines()]
start = main[0]['ts']
metrics = measure(root/'run')
Path('.scratch/audit_94e_metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
print('METRICS', json.dumps(metrics, ensure_ascii=False))
for p in [traces/'main_agent.jsonl', *sorted((traces/'subagents').glob('*.jsonl'))]:
    print('\nAGENT', p.name)
    for r in map(json.loads, p.read_text().splitlines()):
        if r['t'] == 'llm':
            for c in r.get('tool_calls', []):
                print('CALL', round(r['ts']-start,2), r.get('turn'), c['name'], json.dumps(c.get('args'), ensure_ascii=False))
        if r['t'] == 'result':
            value = r.get('result')
            if r.get('name') == 'corpus_search':
                v = json.loads(value)
                value = {'ok':v.get('ok'), 'hits':v.get('hits',[])[:2], 'coverage':v.get('coverage')}
            print('RESULT',round(r['ts']-start,2),r.get('name'),'error=',r.get('error'),json.dumps(value,ensure_ascii=False))
        if r['t'] in ('end','compaction'):
            print('EVENT',r)
for p in sorted((root/'run/agent/team-results').rglob('*.json')):
    j=json.loads(p.read_text())
    print('JOB', p.name, 'FIELDS', list(j))
    print('ASSIGNMENT',json.dumps(j.get('assignment_metadata'),ensure_ascii=False))
    print('METADATA',json.dumps({k:v for k,v in j.get('metadata',{}).items() if k in ('find_one_published_on','first_date_match','submission_repair_count','verification_events')},ensure_ascii=False))
