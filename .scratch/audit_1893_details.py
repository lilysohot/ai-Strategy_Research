import json
from pathlib import Path
from collections import Counter
root=Path('/home/administrator/.local/share/frontier-agent/web/runs/18937dbdabb1401296a685aeaa747c0b')
base=root/'run/agent/trajectories'
for p in sorted(base.rglob('*.jsonl')):
 rows=[json.loads(s) for s in p.read_text().splitlines()]
 if p.stem=='main_agent':
  for r in rows:
   if r['t']=='llm':
    for c in r.get('tool_calls',[]):
     if c['name']=='assign_task':
      print('ASSIGN',r['turn'],'topkeys',list(c['args']))
      for t in c['args'].get('tasks',[]):
       print('ASSIGN_TASK',t.get('agent'), 'checks',[(x.get('check_id'),len(x.get('subject',{}).get('text','')), x.get('revision_kind'),[e.get('job_id') for e in x.get('evidence',[])]) for x in t.get('verification_checks',[])])
 if 'research.t01' in p.stem:
  for r in rows:
   if r['t']=='result' and r.get('name')=='web_fetch':
    s=str(r.get('result',''))
    print('FETCH',p.stem,'len',len(s),'650m', '6.5' in s, 'text',s[:190].replace('\n',' '))
   if r['t']=='llm':
    for c in r.get('tool_calls',[]):
     if c['name']=='submit_report':
      txt=c['args'].get('content','')
      for line in txt.splitlines():
       if any(x in line for x in ['6.5','650','60亿','60 亿','11.82']): print('REPORT_NUMBER',p.stem,line[:600])
 for r in rows:
  if r['t']=='llm' and not r.get('tool_calls') and 'verifier' in p.stem:
   print('NO_TOOL',p.stem,r.get('turn'),str(r.get('content',''))[:350], 'keys',list(r))
for p in sorted(Path('.scratch').glob('audit_1893_claims*bound.txt')):
 records=[]
 for line in p.read_text().splitlines():
  if line.startswith('{"source_job":'):
   records.append(json.loads(line))
 print('WEB_BOUND',p.name,'total',len(records),'by_job',dict(Counter((r['source_job'], bool(r.get('text_omitted'))) for r in records)),'kind',dict(Counter(r['content_kind'] for r in records)))
