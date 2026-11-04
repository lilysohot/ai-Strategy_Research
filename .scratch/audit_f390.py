import json
from pathlib import Path
from collections import Counter

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/f39019b418d247598b0879f69f68a937')
base = root / 'run/agent/trajectories'
for path in sorted(base.rglob('*.jsonl')):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    print('\nTRACE', path.name, 'turns', sum(r['t']=='llm' for r in rows), 'events', dict(Counter(r['t'] for r in rows)))
    for number, r in enumerate(rows, 1):
        if r['t']=='llm':
            for call in r.get('tool_calls', []):
                if path.stem=='main_agent' and r.get('turn')==8 and call['name']=='assign_task':
                    print('DISPATCH LINE', number, json.dumps(call.get('args'), ensure_ascii=False))
                if 'verifier' in path.stem and call['name']=='submit_report':
                    args=call.get('args',{})
                    print('VERIFIER SUBMISSION LINE', number, json.dumps(args,ensure_ascii=False)[:15500])
        if r['t']=='result' and r.get('name') in ('corpus_search','corpus_fetch'):
            raw=r.get('result','')
            try: obj=json.loads(raw) if isinstance(raw,str) else raw
            except ValueError: continue
            if r['name']=='corpus_search' and r.get('turn') in (1,2):
                print('SEARCH METADATA', json.dumps({k:v for k,v in obj.items() if k not in ('results','items','hits')},ensure_ascii=False)[:6500])
            if r['name']=='corpus_fetch' and 'verifier' in path.stem:
                for item in obj.get('items',[]):
                    text = item.get('text', item.get('content',''))
                    flat = ''.join(text.split())
                    if any(s in flat for s in ('20–25','20-25','12倍','22倍','微调')):
                        print('SOURCE LINE',number,item.get('chunk_id'),text)
    snapshot=json.loads(path.with_suffix('.json').read_text())
    print('SNAPSHOT KEYS',list(snapshot))
    messages=snapshot.get('messages',[])
    for i,m in enumerate(messages):
        content=m.get('content') or ''
        if not isinstance(content,str): continue
        if m.get('role')=='system':
            print('SYSTEM FLAGS', 'factual_scope' in content, 'publication_excerpt' in content)
        if '[team delivery]' in content or '[team verification repair]' in content:
            print('CONTROL MESSAGE',i,content[:600])
