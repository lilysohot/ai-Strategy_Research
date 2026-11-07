import json
from pathlib import Path
from collections import Counter
from benchmarks.team_workflow.metrics import measure

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/7d0cecf846254f4895d318299136a688')
directory=root/'run/agent/trajectories'
main=[json.loads(x) for x in (directory/'main_agent.jsonl').read_text().splitlines()]
start=main[0]['ts']
print('START',str(main[0])[:10000])
metrics=measure(root/'run')
print('METRICS',json.dumps({k:v for k,v in metrics.items() if k not in ['agents','limitations']},ensure_ascii=False))
for p in [directory/'main_agent.jsonl',*sorted((directory/'subagents').glob('*.jsonl'))]:
    rows=[json.loads(x) for x in p.read_text().splitlines()]
    print('\nAGENT',p.stem,round(rows[0]['ts']-start,1),round(rows[-1]['ts']-start,1))
    for r in rows:
        if r['t']=='llm':
            for c in r.get('tool_calls',[]):
                print('CALL',round(r['ts']-start,1),r.get('turn'),c['name'],json.dumps(c.get('args'),ensure_ascii=False)[:10000 if c['name']=='assign_task' else 1800])
        if r['t']=='result' and (r.get('error') or any(x in str(r.get('result','')) for x in ['Error:','validation error','preflight failed'])):
            print('ERROR',round(r['ts']-start,1),r.get('name'),str(r.get('result'))[:3500])
        if r['t'] in ['end','compaction']:
            print('EVENT',str(r)[:2000])
for p in sorted((root/'run/agent/team-results').rglob('*.json')):
    j=json.loads(p.read_text())
    print('\nJOB',p.name,j.get('agent_name'),j.get('success'),j.keys())
    print('ASSIGN',json.dumps(j.get('assignment_metadata'),ensure_ascii=False)[:16000])
    print('VERDICTS',json.dumps(j.get('metadata',{}).get('verification_events'),ensure_ascii=False))
    print('REPORT',j.get('final_content','')[:16000])
