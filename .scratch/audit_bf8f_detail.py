import json
from pathlib import Path
from collections import Counter

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/bf8f51c91e594a49b9e77a64c5915afe')
summary = json.loads((root/'summary.json').read_text())
print('SUMMARY_KEYS', list(summary))
contract = summary['report_contract']
for check in contract.get('verification_checks', []):
    print('CHECK', json.dumps({k:v for k,v in check.items() if k not in {'attempts','evidence','result'}}, ensure_ascii=False))
    print('VERDICT', json.dumps(check.get('result'),ensure_ascii=False))
base = root/'run/agent/trajectories'
allrows=[]
for p in sorted(base.rglob('*.jsonl')):
    rows=[json.loads(line) for line in p.read_text().splitlines()]
    allrows.extend(rows)
    snap=json.loads(p.with_suffix('.json').read_text())
    print('TRACE',p.name)
    for i,m in enumerate(snap.get('messages',[])):
        c=m.get('content') or ''
        if isinstance(c,str) and (i<2 or 'Tool-delivered corpus evidence' in c):
            print('MESSAGE',i,m.get('role'),len(c),'packet',c.count('Tool-delivered corpus evidence'),'coverage_copies',c.count('unknown_date_sources'))
    if 'verifier' in p.stem:
        for r in rows:
            if r['t']=='llm':
                for c in r.get('tool_calls',[]):
                    if c['name']=='corpus_fetch':print('FETCH_ARGS',json.dumps(c['args'],ensure_ascii=False))
            if r['t']=='result' and r['name'] in {'corpus_fetch','submit_report'}:
                raw=r['result']
                try: d=json.loads(raw)
                except (ValueError,TypeError):d={'raw':str(raw)[:450]}
                print('RESULT',r['name'],json.dumps({k:v for k,v in d.items() if k not in {'text','items','verification_results'}},ensure_ascii=False)[:1000])
                for it in d.get('items',[]):
                    if it.get('error') or it.get('ok') is False:print('FETCH_ERROR',json.dumps(it,ensure_ascii=False))
    if p.stem=='main_agent':
        for r in rows:
            if r['t']=='result' and r['name'] in {'collect_reports','deliver_answer','assign_task'}:
                c=r['result']; pos=c.find('[version-bound checks]')
                print('MAIN_RESULT',r['name'],len(c),'status_chars',len(c)-pos if pos>=0 else 0,'coverage_copies',c.count('unknown_date_sources'),c[:180] if r['name']!='collect_reports' else '')
            if r['t']=='llm':
                for c in r.get('tool_calls',[]):
                    if c['name']=='deliver_answer': print('ANSWER',json.dumps(c['args'],ensure_ascii=False))
print('TOOLS',Counter(r['name'] for r in allrows if r['t']=='result'))
print('ATTEMPTS',Counter((r.get('outcome'),r.get('reason')) for r in allrows if r['t']=='attempt' and r.get('phase')=='finished'))
for rid in ['8eda75f47314494ea7a03c020dd219bb', root.name]:
    s=json.loads((root.parent/rid/'summary.json').read_text())
    print('COMPARE',rid,s['duration_s'],s.get('cache_attempts',{}).get('all_attempts',{}))
