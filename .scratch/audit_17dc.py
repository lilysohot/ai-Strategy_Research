import json
from pathlib import Path
from collections import Counter

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/17dcf7ec7d024064a23788558ea6c5a3')
summary = json.loads((root/'summary.json').read_text())
contract = summary['report_contract']
print('SUMMARY', json.dumps({k:summary.get(k) for k in ['duration_s','answer_status','stopped_by','error']}, ensure_ascii=False))
print('CONTRACT', {k:contract.get(k) for k in ['verification','verification_basis','gaps']})
for j in contract.get('job_outcomes',[]):
    print('JOB', {k:v for k,v in j.items() if k not in {'verification_checks','content_acquisition','verification_events','report','final_content'}})
base = root/'run/agent/trajectories'
start=json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
for p in sorted(base.rglob('*.jsonl')):
    rows=[json.loads(x) for x in p.read_text().splitlines()]
    print('\nTRACE',p.name,'EVENTS',dict(Counter(r['t'] for r in rows)))
    print('TOOLS',dict(Counter(r.get('name') for r in rows if r['t']=='result')))
    for n,r in enumerate(rows,1):
        elapsed=round(r.get('ts',start)-start,2)
        if r['t']=='llm':
            calls=r.get('tool_calls',[])
            print('LLM',n,elapsed,'turn',r.get('turn'),'tools',[c['name'] for c in calls], 'usage',r.get('usage'))
            for c in calls:
                if p.stem=='main_agent' and c['name'] in {'assign_task','collect_reports','create_subagent','update_task','deliver_answer'}:
                    a=c.get('args',{}).copy()
                    if c['name']=='deliver_answer': a={k:v for k,v in a.items() if k!='content'}
                    if c['name']=='assign_task':
                        a={'tasks':[{k:v for k,v in t.items() if k!='prompt' and k!='verification_checks'} | {'prompt_len':len(t.get('prompt','')),'checks':[{'check_id':x.get('check_id'),'subject_len':len(x.get('subject',{}).get('text','')),'evidence':x.get('evidence'),'factual_scope':x.get('factual_scope'),'publication_excerpt':x.get('publication_excerpt'),'replaces_job_id':x.get('replaces_job_id')} for x in t.get('verification_checks',[])]} for t in a.get('tasks',[])]}
                    print('CALL',json.dumps(a,ensure_ascii=False)[:6500])
        elif r['t']=='result' and (p.stem=='main_agent' or 'verifier' in p.stem):
            print('RESULT',n,elapsed,r.get('name'),str(r.get('result'))[:1800])
        elif r['t'] in {'end','error','cancelled','retry'} or (r['t']=='attempt' and r.get('outcome') not in {'','accepted'}):
            print('CONTROL',n,elapsed,json.dumps(r,ensure_ascii=False)[:2000])
    snap=json.loads(p.with_suffix('.json').read_text())
    print('SNAPSHOT', {k:snap.get(k) for k in ['turns_used','tool_calls_count','stopped_by']})
    for idx,m in enumerate(snap.get('messages',[])):
        txt=m.get('content') or ''
        if isinstance(txt,str) and any(x in txt for x in ['[required verification ready]','[team phase','[team delivery]','[team verification repair]']):
            print('INJECT',idx,txt[:1800])



