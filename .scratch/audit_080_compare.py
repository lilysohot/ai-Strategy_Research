import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta

ROOT = Path('/home/administrator/.local/share/frontier-agent/web/runs')
for run in ['bf9d5de507b54b519173c08c1746cb71', '080ad8521962429a814171f48ffc7f60']:
    r = ROOT / run
    s = json.loads((r / 'summary.json').read_text())
    d = r / 'run/agent/trajectories'
    rows = [json.loads(x) for x in (d / 'main_agent.jsonl').read_text().splitlines()]
    start = rows[0]['ts']
    a = s['cache_attempts']['all_attempts']
    print('RUN', run, 'duration', s['duration_s'], 'LOCAL', datetime.fromtimestamp(start, timezone(timedelta(hours=8))))
    print('METRICS', {k:a[k] for k in ['attempts','known_prompt_tokens','known_cache_read_tokens','unknown_usage_attempts']}, 'uncached', a['known_prompt_tokens']-a['known_cache_read_tokens'])
    calls = Counter()
    for p in [d/'main_agent.jsonl', *sorted((d/'subagents').glob('*.jsonl'))]:
        events = [json.loads(x) for x in p.read_text().splitlines()]
        first, last = events[0], events[-1]
        print('TIMELINE', p.stem, round(first['ts']-start,1), round(last.get('ts',first['ts'])-start,1))
        for e in events:
            if e.get('t') == 'llm':
                for c in e.get('tool_calls',[]):
                    calls[c['name']] += 1
                    if run.startswith('080') and p.stem=='main_agent' and c['name']=='assign_task':
                        for task in c.get('args',{}).get('tasks',[]):
                            print('DISPATCH',e.get('turn'),str(task.get('prompt'))[:1500])
            if e.get('t') == 'attempt' and e.get('reason'):
                print('ATTEMPT_ISSUE',p.stem,e.get('reason'),e.get('duration_ms'))
            if e.get('t')=='result' and any(x in str(e.get('result','')) for x in ['Error:','preflight failed','validation error','extra_forbidden']):
                print('TOOL_ERROR',p.stem,e.get('name'),str(e.get('result',''))[:1800])
    print('CALLS',dict(calls))
    kinds=Counter()
    for p in (r/'run/agent/team-results').rglob('*.json'):
        j=json.loads(p.read_text())
        kinds.update(x.get('content_kind') for x in j['metadata'].get('web_evidence',[]))
    print('EVIDENCE_KINDS',dict(kinds))
    if not run.startswith('080'):
        continue
    for p in sorted((d/'subagents').glob('verifier*.json')):
        t=json.loads(p.read_text())
        for m in t['messages']:
            text=m.get('content') or ''
            if not isinstance(text,str) or '# Tool-delivered web evidence' not in text:
                continue
            print('PROMPT',p.name,len(text),'omitted',text.count('"text_omitted": true'),'excerpt',text.count('"text_excerpt": true'))
            if p.name=='verifier_facts.t04.json':
                lines=text.split('# Tool-delivered web evidence')[1].splitlines()
                for i,line in enumerate(lines):
                    if line.startswith('{') and 'U.S._Senate' in line:
                        print('SENATE_POINTER',line)
                        body=[]
                        for line2 in lines[i+1:]:
                            if line2.startswith('{') or line2.startswith('Omitted web'):break
                            body.append(line2)
                        print('SENATE_ATTACHED_BODY','\n'.join(body))
