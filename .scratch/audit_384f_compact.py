import json,re
from pathlib import Path
root=Path('/home/administrator/.local/share/frontier-agent/web/runs/384fd87e9b974c678eacb28e083c9807')
base=root/'run/agent/trajectories'
start=json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
for p in sorted(base.rglob('*.jsonl')):
 rows=list(map(json.loads,p.read_text().splitlines()))
 if 'impact_research' in p.name:
  delivered='\n'.join(str(r.get('result','')) for r in rows if r.get('name') in ('corpus_search','corpus_fetch'))
  for r in rows:
   tm=round(r.get('ts',start)-start,2)
   if r['t']=='llm':
    for c in r.get('tool_calls',[]):
     if c['name']=='corpus_submit_manifest':
      a=c['args'];refs=[e['evidence_ref'] for con in a.get('conclusions',[]) for e in con.get('evidence',[]) if 'evidence_ref'in e]
      print('MANIFEST',tm,'report',a.get('report_path'),'n',len(a.get('conclusions',[])),'refs not returned',[(x,len(x)) for x in refs if x not in delivered])
   if r['t']=='result' and r.get('name')=='corpus_submit_manifest':
    d=json.loads(r['result']); print('RESULT',tm,{k:d.get(k) for k in ('ok','errors','evidence_status','report_bound','publish_status','counts')},'issues',[(c['id'],c['status'],c.get('problems')) for c in d.get('conclusions',[]) if c['status']!='supported'])
  for target in ['25ce580','95f3ad338','10 到 50','10到50','10-50','10–50','8000','2.90']:
   print('SOURCE_TERM',target)
   count=0
   for r in rows:
    if r['t']=='result' and r.get('name') in ('corpus_search','corpus_fetch'):
     txt=str(r['result'])
     for m in re.finditer(re.escape(target),txt):
      print(round(r['ts']-start,2),r['name'],txt[max(0,m.start()-120):m.end()+180]);count+=1
      if count>=6:break
     if count>=6:break
  snap=json.loads(p.with_suffix('.json').read_text())
  print('SNAPKEYS',list(snap))
  prompt_tokens=sum(r.get('usage',{}).get('prompt_tokens',0) for r in rows if r['t']=='llm' and 224<r['ts']-start<284)
  print('MANIFEST_PHASE_INPUT_TOKENS',prompt_tokens)
for p in sorted((root/'run/corpus/manifests').glob('*.json')):
 d=json.loads(p.read_text());print('MANIFEST_FILE',p.name,'owner',d.get('owner_role'),'ids',[c['id'] for c in d['conclusions']])
from plugins.corpus.ledger import _merge_manifests
loaded=[(p,json.loads(p.read_text())) for p in sorted((root/'run/corpus/manifests').glob('*.json'))]
print('MERGED_IDS',[c['id'] for c in _merge_manifests(loaded)['conclusions']])
for p in (root/'run/corpus').glob('*.json'):
 if p.name=='ledger.json':continue
 d=json.loads(p.read_text()); print('CORPUS_META',p.name,{k:d.get(k) for k in ['status','counts','verification_errors']})
