import json
from pathlib import Path
from collections import Counter

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/17dcf7ec7d024064a23788558ea6c5a3')
base=root/'run/agent/trajectories'
start=json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
s=json.loads((root/'summary.json').read_text())
print('FINAL',s['final_answer'])
print('CACHE',json.dumps(s.get('cache_attempts',{}).get('all_attempts',{})))
for ch in s['report_contract'].get('verification_checks',[]):
    print('CHECK',ch['check_id'],ch['verdict'],'SUBJECT',ch['subject'].get('text',''))
    print('DETAIL',json.dumps(ch.get('result'),ensure_ascii=False))
for p in sorted(base.rglob('*.jsonl')):
    rows=[json.loads(x) for x in p.read_text().splitlines()]
    finishes=[r for r in rows if r['t']=='attempt' and r.get('phase')=='finished']
    calls=[r for r in rows if r['t']=='llm']
    tools=[r for r in rows if r['t']=='result']
    print('\nAGENT',p.name,'start',round(rows[0]['ts']-start,2),'end',round(rows[-1]['ts']-start,2),
          'wall',round(rows[-1]['ts']-rows[0]['ts'],2),'llm_s',round(sum(r.get('duration_ms',0) or 0 for r in finishes)/1000,2),
          'ttft_s',round(sum(r.get('ttft_ms',0) or 0 for r in finishes)/1000,2),
          'prompt_tokens',sum(r.get('usage',{}).get('prompt_tokens',0) for r in finishes),
          'output_tokens',sum(r.get('usage',{}).get('completion_tokens',0) for r in finishes),
          'max_prompt',max(r.get('usage',{}).get('prompt_tokens',0) for r in calls),'tools',dict(Counter(r['name'] for r in tools)))
    for r in rows:
        at=round(r['ts']-start,2)
        if r['t']=='attempt' and r.get('phase')=='finished':
            print('LLM_TIME',at,'turn',r['turn'],'duration_s',round((r.get('duration_ms') or 0)/1000,2),'ttft_s',round((r.get('ttft_ms') or 0)/1000,2),'out',r.get('usage',{}).get('completion_tokens'),'outcome',r.get('outcome'),r.get('reason',''))
        if r['t']=='result':
            raw=r.get('result','')
            print('TOOL',at,r['name'],'ms',r.get('duration_ms'),'chars',len(raw),'error',str(raw)[:200] if ('Error:' in raw or '"ok":false' in raw or '"ok": false' in raw) else '')
        if r['t']=='llm':
            for c in r.get('tool_calls',[]):
                a=c.get('args',{})
                if c['name']=='assign_task':print('ASSIGN',at,[{'agent':t.get('agent'),'checks':[k.get('check_id') for k in t.get('verification_checks',[])]} for t in a.get('tasks',[])])
                elif c['name']=='submit_report': print('SUBMIT',at,'content_chars',len(a.get('content','')),'finish',a.get('finish'),'verdicts',[(v.get('check_id'),v.get('verdict')) for v in a.get('verification_results',[])])
    snapshot=json.loads(p.with_suffix('.json').read_text())
    for i,m in enumerate(snapshot.get('messages',[])):
        c=m.get('content') or ''
        if isinstance(c,str) and m.get('role')=='user':
            print('INPUT',i,len(c),c[:300].replace('\n',' '))

