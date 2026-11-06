import json
from pathlib import Path
from collections import Counter
from plugins.tools._corpus_scope import corpus_scope_findings

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/fbc883771ed84ca3be2d5eceab5dd218')
summary = json.loads((root/'summary.json').read_text())
contract = summary['report_contract']
base = root/'run/agent/trajectories'
start = json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
print('REPLAY', summary.get('replay'))
print('BOUNDARY', summary.get('evidence_boundary'))
v = json.loads((root/'run/corpus/manifest_verification.json').read_text())
print('MANIFEST_KEYS', list(v))
print('MANIFEST', json.dumps({k:v.get(k) for k in ['status','counts','verification_errors','boundary_answer_status','report_chars','all_offered_fetched','warnings','errors']},ensure_ascii=False))
for p in (root/'run/corpus/manifests').glob('*.json'):
    m=json.loads(p.read_text())
    print('MANIFEST_FILE', p.name,'conclusions',len(m.get('conclusions',[])),'target',m.get('report_target'),'keys',list(m))
    if m.get('report_target')=='final_answer':
        print('FINAL_CLAIMS',json.dumps([{k:c.get(k) for k in ['id','report_quote','evidence']} for c in m.get('conclusions',[])],ensure_ascii=False)[:4000])
for check in contract['verification_checks']:
    print('CHECK', check['check_id'],check['verdict'],check.get('factual_scope'),check.get('publication_excerpt'))
    for attempt in check['attempts']:
        print('CHECK_ATTEMPT',json.dumps(attempt,ensure_ascii=False)[:1700])
for p in sorted(base.rglob('*.jsonl')):
    rows = [json.loads(s) for s in p.read_text().splitlines()]
    attempts=[r for r in rows if r.get('t')=='attempt' and r.get('phase')=='finished']
    usage=[r['usage'] for r in attempts if r.get('usage')]
    print('AGENT',p.stem,'input',sum(u.get('prompt_tokens',0) for u in usage),'output',sum(u.get('completion_tokens',0) for u in usage),
        'first_input',usage[0].get('prompt_tokens') if usage else None,'max_input',max((u.get('prompt_tokens',0) for u in usage),default=0),
        'models',list({u.get('model') for u in usage}),'llm_s',round(sum(r.get('duration_ms',0) for r in attempts)/1000,3))
    for n,r in enumerate(rows,1):
        if r['t']=='attempt' and r.get('phase')=='finished' and r.get('outcome')!='accepted':
            print('BAD_ATTEMPT',n,{k:r.get(k) for k in ['turn','reason','duration_ms','outcome']})
        if r['t']=='llm':
            for c in r.get('tool_calls',[]):
                if c['name']=='deliver_answer':
                    a=c['args']
                    print('DELIVERY',n,r['turn'],round(r['ts']-start,2),'chars',len(a.get('content','')),'claims',len(a.get('corpus_conclusions') or []))
                    Path(f'.scratch/audit_fbc8_delivery_t{r["turn"]}.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
                if c['name']=='submit_report' and 'verify' in p.stem:
                    print('VERDICT',r['turn'],json.dumps(c['args'].get('verification_results'),ensure_ascii=False)[:1700])
        if r['t']=='result' and (str(r.get('result','')).startswith('Error') or 'validation error' in str(r.get('result',''))):
            print('TOOL_ERROR',n,r.get('name'),str(r.get('result',''))[:2000])
    snap=json.loads(p.with_suffix('.json').read_text())
    for idx,m in enumerate(snap['messages']):
        txt=m.get('content') or ''
        if isinstance(txt,str) and '# Bound verification checks' in txt:
            print('CONTEXT',idx,'chars',len(txt),'preview',txt.count('Report preview'),'body_count',txt.count('SOURCE EVIDENCE'),'old_candidate',txt.count('Previous review defects'))
        if isinstance(txt,str) and 'DSML' in txt:
            print('DSML',idx,m.get('role'),txt[:80])
obs=[o for j in contract['job_outcomes'] for o in j.get('content_acquisition',[])]
print('FINAL_SCOPE',corpus_scope_findings(summary['final_answer'],obs))
print('OBS_COUNT',len(obs))
