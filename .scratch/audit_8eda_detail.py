import json
from pathlib import Path
from collections import Counter
root=Path('/home/administrator/.local/share/frontier-agent/web/runs/8eda75f47314494ea7a03c020dd219bb')
base=root/'run/agent/trajectories'
for name in ['main_agent','subagents/claim_verifier.t01']:
    paths=list(base.rglob(name.split('/')[-1]+'.json'))
    p=paths[0]; snap=json.loads(p.read_text())
    print('MESSAGES',p.name)
    for i,m in enumerate(snap['messages']):
        c=m.get('content') or ''
        if not isinstance(c,str):continue
        if len(c)>25000 or i<2 or '[required verification ready]' in c:
            print(i,m.get('role'),m.get('name'),len(c),'corpus_limits=',c.count('corpus_limits'),'coverage=',c.count('unknown_date_sources'),c[:100].replace('\n',' '))
rows=[json.loads(x) for x in (base/'main_agent.jsonl').read_text().splitlines()]
for n,r in enumerate(rows,1):
    if r['t']=='llm' and r['turn'] in [8,9]: print('BADARGS',n,json.dumps(r.get('tool_calls'),ensure_ascii=False)[:1000])
    if r['t']=='result' and r.get('name')=='collect_reports':
        s=r.get('result',''); pos=s.find('[version-bound checks]')
        print('COLLECT',n,'chars',len(s),'checks_chars',len(s)-pos if pos>=0 else 0,'coverage_copies',s.count('unknown_date_sources'))
summary=json.loads((root/'summary.json').read_text())
for check in summary['report_contract']['verification_checks']:
    raw=json.dumps(check,ensure_ascii=False)
    reduced=json.loads(raw)
    for source in [reduced.get('subject',{}), *reduced.get('evidence',[])]:source.pop('corpus_limits',None)
    print('CHECKSIZE',check['check_id'],len(raw),len(json.dumps(reduced,ensure_ascii=False)),'coverage_copies',raw.count('unknown_date_sources'))
p=next(base.rglob('claim_verifier.t01.jsonl'))
for n,line in enumerate(p.read_text().splitlines(),1):
    r=json.loads(line)
    if r['t']=='llm':
        for c in r.get('tool_calls',[]):
            if c['name'] in ['corpus_fetch','submit_report']:print('VERIFIER_CALL',n,c['name'],json.dumps(c.get('args'),ensure_ascii=False)[:1000])
allrows=[json.loads(line) for p in base.rglob('*.jsonl') for line in p.read_text().splitlines()]
print('TOOLS_TOTAL',sum(r['t']=='result' for r in allrows))
for runid in ['f39019b418d247598b0879f69f68a937','8eda75f47314494ea7a03c020dd219bb']:
    s=json.loads((root.parent/runid/'summary.json').read_text())
    print('COMPARE',runid,s['duration_s'],s.get('cache_attempts',{}).get('all_attempts',{}))
