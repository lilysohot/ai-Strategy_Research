import collections
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '/home/administrator/.local/share/frontier-agent/web/runs/580f990b06f24500b43a6276a5f41631')
start = None
for p in sorted((ROOT/'run/agent/trajectories').rglob('*.jsonl')):
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    if p.stem == 'main_agent':
        start = rows[0]['ts']
    results = [r for r in rows if r['t']=='result']
    attempts = [r for r in rows if r['t']=='attempt' and r.get('phase')=='finished']
    print('\nTRACE', p.name, 'wall_s', round(rows[-1]['ts']-rows[0]['ts'], 2),
          'tool_counts', dict(collections.Counter(r['name'] for r in results)))
    print('usage', {key: sum(a.get('usage',{}).get(key,0) or 0 for a in attempts) for key in ('prompt_tokens','completion_tokens','cache_read_tokens')})
    for r in attempts:
        if r.get('outcome') != 'accepted':
            print('DISCARDED', {k:v for k,v in r.items() if k not in ('usage','call_id','attempt_id')})
    args = {c['id']: c for r in rows if r['t']=='llm' for c in r.get('tool_calls',[])}
    for r in results:
        val=r.get('result','')
        content = val if isinstance(val,str) else json.dumps(val,ensure_ascii=False)
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            parsed={}
        if r.get('error') or content.startswith(('Error','{"ok":false')):
            print('TOOL_ERROR', r['name'],r['turn'],content[:650])
        if p.stem == 'main_agent':
            c = args.get(r.get('tool_call_id'),{})
            a=c.get('args',{})
            print('MAIN',round(r['ts']-rows[0]['ts'],1),'turn',r['turn'],r['name'],'ms',r['ms'],
                  'args',str(a)[:200] if r['name']!='assign_task' else [(t.get('agent_name',t.get('agent')),t.get('task','')[:110]) for t in a.get('tasks',[])],
                  'result', content[:180])
        if r['name']=='corpus_search':
            c = args.get(r.get('tool_call_id'),{})
            print('SEARCH', c.get('args',{}), 'count',parsed.get('count'), 'mode', parsed.get('mode',parsed.get('search_mode')), 'status',parsed.get('ok'))
        if r['name']=='corpus_fetch':
            c = args.get(r.get('tool_call_id'),{})
            print('FETCH',c.get('args',{}),'chars',len(content),'ok',parsed.get('ok'))
        if r['name'] in ('corpus_inventory','corpus_describe'):
            print('INVENTORY',content[:1800])
