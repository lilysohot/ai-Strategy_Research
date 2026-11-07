import json
from pathlib import Path
from collections import Counter

ROOT = Path('/home/administrator/.local/share/frontier-agent/web/runs/49e4f04b05ca46fda0ae4e4b71d1636a')
s = json.loads((ROOT / 'summary.json').read_text())
d = ROOT / 'run/agent/trajectories'
start = json.loads((d/'main_agent.jsonl').read_text().splitlines()[0])['ts']
print('METRICS', s['duration_s'], s['cache_attempts']['all_attempts'])
calls = Counter()
for p in [d/'main_agent.jsonl', *sorted((d/'subagents').glob('*.jsonl'))]:
    events = [json.loads(x) for x in p.read_text().splitlines()]
    print('TIMELINE', p.stem, round(events[0]['ts']-start,1), round(events[-1]['ts']-start,1))
    for e in events:
        if e.get('t') == 'llm':
            for c in e.get('tool_calls',[]):
                calls[c['name']] += 1
                if p.stem == 'main_agent':
                    print('MAIN_CALL',round(e['ts']-start,1),e.get('turn'),c['name'],str(c.get('args'))[:14000] if c['name']=='assign_task' else str(c.get('args'))[:350])
        if e.get('t') == 'attempt' and e.get('reason'):
            print('ATTEMPT_ISSUE',p.stem,e.get('reason'),e.get('duration_ms'))
        if e.get('t')=='result' and any(x in str(e.get('result','')) for x in ['Error:','preflight failed','validation error','extra_forbidden']):
            print('TOOL_ERROR',p.stem,e.get('name'),str(e.get('result',''))[:2500])
print('CALLS',dict(calls))
for p in sorted((ROOT/'run/agent/team-results').rglob('*.json'),key=lambda p:int(p.stem.split('.')[-1])):
    j=json.loads(p.read_text()); a=j['assignment_metadata']; m=j['metadata']
    print('JOB',p.name,j['agent_name'],j['success'],'web',len(m.get('web_evidence',[])), 'corpus',len(m.get('corpus_evidence',[])))
    for x in a.get('verification_checks',[]):
        print('CHECK',x['check_id'],x.get('revision_kind'),x.get('calculation_targets'),x.get('replaces_job_id'),'sources',len(x.get('calculation_sources',[])))
        print('SUBJECT',x.get('subject',{}).get('text'))
    for x in m.get('verification_events',[]):
        print('VERDICT',x['check_id'],x['verdict'],'calc',x.get('calculation_checks'), 'DETAIL',x.get('detail'),'METHOD',x.get('method'),'ISSUES',x.get('unresolved_issues'))
    for e in m.get('web_evidence',[]):
        print('WEB',e.get('source_url',e.get('url')),e.get('content_kind'), len(e.get('text','')),list(e) if not e.get('text') else '')
    if not a.get('verification_checks'): print('REPORT',j['final_content'][:25000])
