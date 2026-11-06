import json
from pathlib import Path
from collections import Counter
from benchmarks.team_workflow.metrics import measure

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/6d4a2c7200124b2b9c91c08960133cae')
summary = json.loads((root/'summary.json').read_text())
print('KEYS', list(summary))
print('SUMMARY', json.dumps({k:summary.get(k) for k in ['duration_s','answer_status','stopped_by','error','question','original_question','usage']}, ensure_ascii=False))
metrics = measure(root)
Path('.scratch/audit_6d4a_metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
print('METRICS', json.dumps(metrics, ensure_ascii=False))
answer = summary.get('final_answer') or ''
Path('.scratch/audit_6d4a_answer.txt').write_text(answer)
contract = summary.get('report_contract') or {}
Path('.scratch/audit_6d4a_contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2))
print('CONTRACT', json.dumps({k:v for k,v in contract.items() if k not in ['job_outcomes','verification_checks','work_items','final_content','final_answer','answer','original_candidate','candidate_text','retained_reports']},ensure_ascii=False)[:5000])
for j in contract.get('job_outcomes',[]):
    print('JOB',json.dumps({k:v for k,v in j.items() if k not in ['report','final_content','content_acquisition','verification_checks','verification_events']}, ensure_ascii=False)[:3500])
base = root/'run/agent/trajectories'
start = json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
for p in sorted(base.rglob('*.jsonl')):
    rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    print('\nTRACE',p.name,'EVENTS',dict(Counter(r['t'] for r in rows)))
    for n,r in enumerate(rows,1):
        elapsed=round(r.get('ts',start)-start,2)
        if r['t']=='llm':
            calls=r.get('tool_calls',[])
            print('LLM',n,elapsed,'turn',r.get('turn'),'tools',[c['name'] for c in calls])
            for c in calls:
                if c['name'] in ['assign_task','submit_report','deliver_answer','add_task','update_task']:
                    a=c.get('args',{}).copy()
                    if c['name']=='deliver_answer':
                        a={k:v for k,v in a.items() if k not in ['content','corpus_conclusions']}
                    if c['name']=='submit_report': a.pop('content',None)
                    if c['name']=='assign_task':
                        a={'tasks':[{k:v for k,v in t.items() if k!='prompt'} | {'prompt_chars':len(t.get('prompt',''))} for t in a.get('tasks',[])]}
                    print('CALL',json.dumps(a,ensure_ascii=False)[:9000])
        elif r['t']=='result':
            v=str(r.get('result',''))
            print('RESULT',n,elapsed,r.get('name'),'error',r.get('is_error'),'chars',len(v),v[:650] if p.stem=='main_agent' or 'verifier' in p.stem else '')
        elif r['t']=='attempt' and r.get('phase')=='finished':
            print('ATTEMPT',n,elapsed,{k:r.get(k) for k in ['turn','duration_ms','outcome','reason','recovery_action','usage']})
        elif r['t'] in ['end','error','cancelled','retry']:
            print('CONTROL',n,elapsed,json.dumps(r,ensure_ascii=False)[:1200])
    snapfile=p.with_suffix('.json')
    if snapfile.exists():
        snap=json.loads(snapfile.read_text())
        print('SNAPSHOT_KEYS',list(snap))
        print('SNAPSHOT',{k:snap.get(k) for k in ['turns_used','tool_calls_count','stopped_by']})
        for idx,m in enumerate(snap.get('messages',[])):
            txt=m.get('content') or ''
            if not isinstance(txt,str): continue
            markers=['[required verification ready]','[team delivery]','[team verification repair]','[early research handoff]','# Tool-delivered web evidence']
            for marker in markers:
                if marker in txt:
                    at=txt.index(marker)
                    print('INJECT',idx,marker,txt[at:at+1700])
            if m.get('role')=='user' and idx<3:
                print('USER_START',idx,txt[:1800])
            if '# Bound verification checks' in txt:
                print('BOUND_CONTEXT',idx,'chars',len(txt),'corpus_handoff', '# Tool-delivered corpus evidence' in txt,
                      'web_handoff', '# Tool-delivered web evidence' in txt, 'source_blocks',txt.count('SOURCE EVIDENCE'))
                Path(f'.scratch/audit_6d4a_{p.stem}_bound.txt').write_text(txt)
