import json, re, statistics
from pathlib import Path
root=Path('/home/administrator/.local/share/frontier-agent/web/runs/17dcf7ec7d024064a23788558ea6c5a3')
s=json.loads((root/'summary.json').read_text())
print('SUMMARY_KEYS',list(s))
for check in s['report_contract']['verification_checks']:
    print('CHECK_STATE',json.dumps({'check_id':check['check_id'],'verdict':check['verdict'],'attempts':[{k:a.get(k) for k in ['job_id','execution_status','verdict','revision_kind']} for a in check['attempts']]},ensure_ascii=False))
base=root/'run/agent/trajectories'
start=json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
found=set()
for p in sorted(base.rglob('*.jsonl')):
    rows=[json.loads(x) for x in p.read_text().splitlines()]
    for r in rows:
        if r['t']=='llm':
            for c in r.get('tool_calls',[]):
                if c['name']=='deliver_answer':
                    text=c.get('args',{}).get('content','')
                    for m in re.finditer('全库没有',text):print('REJECTED_PHRASE_CONTEXT',text[max(0,m.start()-100):m.end()+100])
                if c['name']=='assign_task':
                    for t in c.get('args',{}).get('tasks',[]):
                        for ch in t.get('verification_checks',[]):print('BOUND',round(r['ts']-start,2),json.dumps({k:ch.get(k) for k in ['check_id','replaces_job_id','revision_kind','revision_reason','publication_excerpt','factual_scope']},ensure_ascii=False))
        if r['t']=='result' and r.get('name') in ('corpus_fetch','corpus_search'):
            try:data=json.loads(r['result'])
            except (ValueError,TypeError):continue
            def walk(x):
                if isinstance(x,dict):
                    for k,v in x.items():
                        if k in ('text','snippet','content') and isinstance(v,str):yield v
                        elif isinstance(v,(dict,list)):yield from walk(v)
                elif isinstance(x,list):
                    for v in x:yield from walk(v)
            for text in walk(data):
                for term in ('保留时长','25%','4%','16TB'):
                    for m in re.finditer(re.escape(term),text):
                        excerpt=text[max(0,m.start()-160):m.end()+190]
                        if excerpt not in found:
                            found.add(excerpt)
                            print('EVIDENCE',term,excerpt.replace('\n',' '))
log=(root/'run/engine.log').read_text()
ms=[int(x) for x in re.findall(r'✓ corpus_search \((\d+)ms\)',log)]
print('SEARCH_MS',{'n':len(ms),'median':statistics.median(ms),'max':max(ms),'sum':sum(ms)})
print('STALLED_COUNT',len(re.findall('LLM stream stalled:',log)))
print('MODEL', sorted({r.get('usage',{}).get('model','') for p in base.rglob('*.jsonl') for r in map(json.loads,p.read_text().splitlines()) if r['t']=='llm'}))
snap=json.loads((base/'main_agent.json').read_text())
for m in snap['messages']:
    text=m.get('content') or ''
    if isinstance(text,str) and 'Publication time remaining:' in text:
        print('PUBLICATION_REMAINING',re.search(r'Publication time remaining:.*',text).group())
from plugins.tools._corpus_scope import corpus_scope_findings
observations=[{'tool':'corpus_search','obtained':True,'coverage':{'processing':'partial','availability':'unknown'}}]
for r in map(json.loads,(base/'main_agent.jsonl').read_text().splitlines()):
    if r['t']=='llm':
        for c in r.get('tool_calls',[]):
            if c['name']=='deliver_answer':
                findings=corpus_scope_findings(c.get('args',{}).get('content',''),observations)
                print('DELIVERY_GUARD_REPLAY',round(r['ts']-start,2),json.dumps(findings,ensure_ascii=False))
